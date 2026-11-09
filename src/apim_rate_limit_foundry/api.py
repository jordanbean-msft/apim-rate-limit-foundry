import csv
import io
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from redis.exceptions import RedisError

from apim_rate_limit_foundry.auth import Identity, authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.reports.dashboard import DashboardPeriod, DashboardService
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict, Record, RecoveryRequired
from apim_rate_limit_foundry.telemetry import emit


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    dashboard: DashboardService | None = None,
) -> FastAPI:
    config = settings or Settings()
    runtime: Runtime | None = None

    def get_runtime() -> Runtime:
        nonlocal runtime
        if runtime is None:
            runtime = Runtime(config)
        return runtime

    def get_engine() -> Engine:
        return engine if engine is not None else get_runtime().engine

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if runtime:
            await runtime.close()

    app = FastAPI(title="AI Monthly Budget Gateway", lifespan=lifespan)
    app.add_middleware(RequestTelemetryMiddleware)
    app.state.get_engine = get_engine

    def identity(request: Request) -> Identity:
        return authenticate(request, config)

    Auth = Annotated[Identity, Depends(identity)]  # noqa: N806

    @app.exception_handler(Conflict)
    async def conflict_handler(request: Request, error: Conflict) -> JSONResponse:
        emit("request_rejected", level=logging.WARNING, error_type="Conflict", http_status=409)
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def invalid_handler(request: Request, error: ValueError) -> JSONResponse:
        emit("request_rejected", level=logging.WARNING, error_type="ValueError", http_status=400)
        return JSONResponse(status_code=400, content={"detail": str(error)})

    async def unavailable_handler(request: Request, error: Exception) -> JSONResponse:
        emit(
            "limiter_dependency_unavailable",
            level=logging.ERROR,
            error_type=type(error).__name__,
            http_status=503,
            allowed=False,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Budget service unavailable; request denied"},
        )

    for error_type in (OSError, AzureError, RedisError, RecoveryRequired):
        app.add_exception_handler(error_type, unavailable_handler)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal budget service error"},
            headers={"X-Correlation-ID": request.state.correlation_id},
        )

    @app.get("/api/health")
    async def health() -> Record:
        return {"status": "ok", "cloud": config.azure_cloud}

    @app.get("/api/dashboard")
    async def dashboard_tiles(
        request: Request, actor: Auth, period: DashboardPeriod = "24h"
    ) -> list[Record]:
        actor.require("RateLimit.Admin")
        if (
            set(request.query_params) - {"period"}
            or len(request.query_params.getlist("period")) > 1
        ):
            raise HTTPException(400, "Only a single dashboard period is accepted")
        service = dashboard if dashboard is not None else get_runtime().dashboard
        if service is None:
            raise HTTPException(503, "Dashboard telemetry is not configured")
        try:
            return await service.fetch(period)
        except (AzureError, ValueError, KeyError, TypeError, TimeoutError) as error:
            emit("dashboard_unavailable", level=logging.WARNING, error_type=type(error).__name__)
            raise HTTPException(503, "Dashboard telemetry is unavailable. Retry later.") from error

    @app.post("/api/budgets/check")
    async def check_budget(body: BudgetCheck, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().check(body)

    @app.post("/api/usage/record")
    async def record_usage(body: UsageRecordRequest, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().record_usage(body)

    @app.post("/api/counters/rebuild")
    async def rebuild_counters(actor: Auth) -> Record:
        actor.require("RateLimit.Admin")
        count = await get_engine().rebuild_counters()
        emit("counter_projection_rebuilt", records=count)
        return {"records": count, "status": "rebuilt"}

    @app.get("/api/models")
    async def registered_models(actor: Auth) -> list[Record]:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if "RateLimit.Admin" not in actor.roles:
            assignment = await get_engine()._assignment(actor.tenant_id, actor.principal_id)
            if assignment is None:
                return []
        return [
            {
                "id": key,
                "model": key.partition(":")[2],
                "api_protocol": deployment.api_protocol,
                "deployment_name": deployment.model,
                "price_version": deployment.price_version,
                "max_input_tokens": deployment.max_input_tokens,
                "max_output_tokens": deployment.max_output_tokens,
            }
            for key, deployment in sorted(config.model_registry.items())
        ]

    @app.get("/api/usage")
    async def usage(actor: Auth) -> list[Record]:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        return await get_engine().usage(
            actor.tenant_id, actor.principal_id, "RateLimit.Admin" in actor.roles
        )

    @app.get("/api/budgets/status")
    async def budget_status(actor: Auth) -> list[Record]:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        return await get_engine().budget_status(
            actor.tenant_id, actor.principal_id, "RateLimit.Admin" in actor.roles
        )

    @app.get("/api/chargeback", response_model=None)
    async def chargeback(
        actor: Auth,
        month: str,
        format: Literal["json", "csv"] = "json",
    ) -> list[Record] | Response:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None:
            raise HTTPException(400, "Month must use YYYY-MM")
        principal = None if "RateLimit.Admin" in actor.roles else actor.principal_id
        rows = await get_engine().chargeback(actor.tenant_id, month, principal)
        if format == "json":
            return rows
        output = io.StringIO(newline="")
        fields = [
            "business_unit",
            "cost_center",
            "department_id",
            "team_id",
            "user_ref",
            "subscription_id",
            "model",
            "month",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "cost_micro_usd",
            "unknown_requests",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="chargeback-{month}.csv"'},
        )

    @app.get("/api/{collection}")
    async def listing(collection: str, actor: Auth) -> list[Record]:
        if collection not in ("budgets", "organizations", "assignments", "prices"):
            raise HTTPException(404)
        actor.require("RateLimit.Admin")
        return [
            row
            for row in await get_engine().configuration(collection)
            if row.get("tenant_id", actor.tenant_id) == actor.tenant_id
        ]

    @app.put("/api/{collection}/{record_id}")
    async def save_configuration(
        collection: str, record_id: str, body: Record, actor: Auth
    ) -> Record:
        actor.require("RateLimit.Admin")
        if collection not in ("budgets", "organizations", "assignments", "prices"):
            raise HTTPException(404)
        result = await get_engine().save_configuration(
            collection, record_id, body, actor.tenant_id, actor.principal_id
        )
        emit("configuration_written", action="put", collection=collection, status="ok")
        return result

    @app.delete("/api/{collection}/{record_id}")
    async def delete_configuration(collection: str, record_id: str, actor: Auth) -> Record:
        actor.require("RateLimit.Admin")
        if collection not in ("budgets", "organizations", "assignments", "prices"):
            raise HTTPException(404)
        await get_engine().delete_configuration(
            collection, record_id, actor.tenant_id, actor.principal_id
        )
        emit("configuration_written", action="delete", collection=collection, status="ok")
        return {"deleted": record_id}

    return app
