"""HTTP contracts for gateway decisions, administration and accounting reports.

Gateway endpoints accept APIM's authenticated identity and return decision/event
objects. Portal endpoints authorize the signed-in actor, not caller-supplied tenant
IDs. Live budget status comes from Redis; usage and chargeback read best-effort
Table mirrors and can therefore lag or omit accepted traffic.
"""

import csv
import io
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from azure.core.exceptions import AzureError, ServiceResponseTimeoutError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from redis.exceptions import RedisError

from apim_rate_limit_foundry.auth import Identity, authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import CONFIG_MODELS, Engine
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.reports.dashboard import DashboardPeriod, DashboardService
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict, Record
from apim_rate_limit_foundry.telemetry import emit

MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    dashboard: DashboardService | None = None,
) -> FastAPI:
    """Build the API, optionally injecting an engine/dashboard for isolated tests.

    Cloud clients are constructed on demand rather than during route registration.
    Pydantic validates typed request bodies before a handler runs (HTTP 422);
    domain validation, conflicts and dependency failures map to 400, 409 and 503.
    """
    config = settings or Settings()
    runtime: Runtime | None = None

    def get_runtime() -> Runtime:
        """Share one lazily created set of clients for this application instance."""
        nonlocal runtime
        if runtime is None:
            runtime = Runtime(config)
        return runtime

    def get_engine() -> Engine:
        return engine if engine is not None else get_runtime().engine

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Allow a bounded write-behind drain before releasing owned cloud clients."""
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
        """Return HTTP 409 with a detail string for conflicting domain state."""
        emit("request_rejected", level=logging.WARNING, error_type="Conflict", http_status=409)
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def invalid_handler(request: Request, error: ValueError) -> JSONResponse:
        """Return HTTP 400 for a semantically invalid operation or configuration."""
        emit("request_rejected", level=logging.WARNING, error_type="ValueError", http_status=400)
        return JSONResponse(status_code=400, content={"detail": str(error)})

    async def unavailable_handler(request: Request, error: Exception) -> JSONResponse:
        """Fail closed with HTTP 503 rather than admitting against missing state."""
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

    for error_type in (OSError, AzureError, RedisError):
        app.add_exception_handler(error_type, unavailable_handler)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        """Return a generic HTTP 500 and correlation ID without exposing internals."""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal budget service error"},
            headers={"X-Correlation-ID": request.state.correlation_id},
        )

    @app.get("/api/health")
    async def health() -> Record:
        """Return status and Azure cloud selection, without probing dependencies.

        This is process health, not proof that Redis, Table or the provider works;
        deployed platform authentication still applies before this route is reached.
        """
        return {"status": "ok", "cloud": config.azure_cloud}

    @app.get("/api/dashboard")
    async def dashboard_tiles(
        request: Request, actor: Auth, period: DashboardPeriod = "24h"
    ) -> list[Record]:
        """Return fixed deployed dashboard tiles for an administrator.

        The only query parameter is one period: ``1h``, ``24h`` (default) or ``7d``.
        HTTP 200 contains tile metadata, columns, rows, truncation and per-tile
        errors; unavailable tiles must not be interpreted as zero activity.
        Invalid query keys yield 400; unavailable dashboard configuration or a
        failed overall fetch yields 503; a query or overall deadline timeout yields
        504. Arbitrary KQL/workspace input is rejected.
        """
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
        except (TimeoutError, ServiceResponseTimeoutError) as error:
            emit("dashboard_timeout", level=logging.WARNING, error_type=type(error).__name__)
            raise HTTPException(504, "Dashboard telemetry timed out. Retry later.") from error
        except (AzureError, ValueError, KeyError, TypeError) as error:
            emit("dashboard_unavailable", level=logging.WARNING, error_type=type(error).__name__)
            raise HTTPException(503, "Dashboard telemetry is unavailable. Retry later.") from error

    @app.post("/api/budgets/check")
    async def check_budget(body: BudgetCheck, actor: Auth) -> Record:
        """Evaluate an authenticated gateway's request without waiting for Table.

        JSON supplies request/tenant/principal/subscription IDs, a model alias,
        API protocol and streaming flag. HTTP 200 returns request_id, allowed,
        reason, denied_budget_ids, reset_at and retry_after; a monthly denial is
        still a successful decision here, which APIM translates into HTTP 429.
        Request-ID conflicts yield 409; unavailable operational state yields 503.
        Admission checks current spend, not a reservation for future token cost.
        """
        actor.require("RateLimit.Gateway")
        return await get_engine().check(body)

    @app.post("/api/usage/record")
    async def record_usage(body: UsageRecordRequest, actor: Auth) -> Record:
        """Finalize gateway usage in Redis and schedule its best-effort mirror.

        JSON supplies request_id, status and the original provider_usage object
        for actual usage. HTTP 200 returns ``event`` and ``replayed``; it confirms
        Redis accounting, not durable Table persistence or Event Hub delivery.
        Unknown usage remains unpriced. Conflicting replay/context yields 409.
        """
        actor.require("RateLimit.Gateway")
        return await get_engine().record_usage(body)

    @app.get("/api/models")
    async def registered_models(actor: Auth) -> list[Record]:
        """List protocol/alias IDs, deployments, price versions and token bounds.

        Admins see the registry; readers need an enabled assignment or receive
        an empty list. Provider credentials and endpoints are never returned.
        """
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if "RateLimit.Admin" not in actor.roles and not await get_engine().has_assignment(
            actor.tenant_id, actor.principal_id
        ):
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
    async def usage(actor: Auth, month: str | None = None) -> list[Record]:
        """Return eventually persisted tenant usage for ``month=YYYY-MM`` (default: current).

        Restricted to the caller's own events for readers. Invalid month syntax
        yields 400.
        """
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if month is not None and MONTH_PATTERN.fullmatch(month) is None:
            raise HTTPException(400, "Month must use YYYY-MM")
        return await get_engine().usage(
            actor.tenant_id, actor.principal_id, "RateLimit.Admin" in actor.roles, month
        )

    @app.get("/api/budgets/status")
    async def budget_status(actor: Auth) -> list[Record]:
        """Return applicable live Redis totals, limits and remaining micro-USD.

        Admins see tenant budgets; readers see budgets applicable to themselves.
        These approximate operational totals may differ from durable usage reports.
        """
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
        """Aggregate durable usage for ``month=YYYY-MM`` as JSON or CSV.

        ``format`` defaults to JSON; CSV uses a fixed column order and attachment
        name. Admins see the tenant, readers only their own usage. Unknown usage
        contributes unknown_requests rather than fabricated zero-cost counters.
        Invalid month syntax yields 400; unsupported typed query values yield 422.
        """
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if MONTH_PATTERN.fullmatch(month) is None:
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
            "cache_write_tokens",
            "cost_basis",
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
        """Return tenant-scoped active configuration records to admins only.

        Supported collections are budgets, organizations, assignments and prices;
        unknown collection names return 404. Record schemas match the PUT bodies.
        """
        if collection not in CONFIG_MODELS:
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
        """Validate and durably upsert one admin configuration record plus audit.

        The path identifies collection/record ID; JSON must satisfy that collection's
        schema and the authenticated tenant's relationships. The response is the
        saved record. Redis configuration is invalidated after the durable mutation;
        unlike admission/usage mirrors, this operation waits for its Table write.
        """
        actor.require("RateLimit.Admin")
        if collection not in CONFIG_MODELS:
            raise HTTPException(404)
        result = await get_engine().save_configuration(
            collection, record_id, body, actor.tenant_id, actor.principal_id
        )
        emit("configuration_written", action="put", collection=collection, status="ok")
        return result

    @app.delete("/api/{collection}/{record_id}")
    async def delete_configuration(collection: str, record_id: str, actor: Auth) -> Record:
        """Tombstone an admin record and return ``{"deleted": record_id}``.

        Relationship checks prevent deleting referenced organizations. The durable
        mutation/audit completes before Redis invalidation; usage history is retained.
        """
        actor.require("RateLimit.Admin")
        if collection not in CONFIG_MODELS:
            raise HTTPException(404)
        await get_engine().delete_configuration(
            collection, record_id, actor.tenant_id, actor.principal_id
        )
        emit("configuration_written", action="delete", collection=collection, status="ok")
        return {"deleted": record_id}

    return app
