import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.auth import Identity, authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine, event
from apim_rate_limit_foundry.models import (
    Assignment,
    Contract,
    Decision,
    OperationBind,
    OperationCheck,
    Policy,
    Price,
    Release,
    Reserve,
    Settle,
    UsageSummary,
)
from apim_rate_limit_foundry.models.caller_usage import CallerUsage
from apim_rate_limit_foundry.reports.caller_usage import CallerUsageService
from apim_rate_limit_foundry.reports.dashboard import DashboardPeriod, DashboardService
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService
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

    app = FastAPI(title="AI Rate Limiter", lifespan=lifespan)
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
            content={
                "detail": "Limiter unavailable; admission denied; recovery may be required",
            },
        )

    for error_type in (OSError, AzureError, RedisError, RecoveryRequired):
        app.add_exception_handler(error_type, unavailable_handler)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        # ServerErrorMiddleware handles unexpected failures outside user middleware.
        # Retain correlation on its response without disclosing exception messages.
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal limiter error; admission denied"},
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

    @app.post("/api/decisions/reserve")
    async def reserve(body: Reserve, actor: Auth) -> Decision:
        actor.require("RateLimit.Gateway")
        return await get_engine().reserve(body)

    @app.post("/api/decisions/settle")
    async def settle(body: Settle, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().settle(body)

    @app.post("/api/decisions/release")
    async def release(body: Release, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().release(body.reservation_id)

    @app.post("/api/operations/bind")
    async def bind(body: OperationBind, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().bind_operation(body.model_dump(mode="json"))

    @app.post("/api/operations/check")
    async def check(body: OperationCheck, actor: Auth) -> Record:
        actor.require("RateLimit.Gateway")
        return await get_engine().check_operation(body.model_dump(mode="json"))

    @app.post("/api/reconciliation/recover")
    async def recover(actor: Auth) -> Record:
        actor.require("RateLimit.Admin")
        return await get_engine().recover()

    @app.get("/api/models")
    async def registered_models(actor: Auth) -> list[Record]:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        if "RateLimit.Admin" not in actor.roles and not await reader_assignments(actor):
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

    @app.get("/api/usage/summary")
    async def usage_summary(
        actor: Auth,
        period: Literal["hour", "day"] = "day",
    ) -> list[UsageSummary]:
        """Derive UTC admission-time ledger totals, applying available settlements.

        Unresolved admitted requests contribute conservative reserved maxima.
        These are not live Redis balances; unconfirmed intents without an
        admission event are excluded.
        """
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        return await UsageSummaryService(get_engine().repository).summarize(
            period,
            actor.tenant_id,
            actor.principal_id,
            "RateLimit.Admin" in actor.roles,
        )

    @app.get("/api/usage/callers")
    async def caller_usage(
        actor: Auth,
        period: Literal["hour", "day"] = "day",
    ) -> list[CallerUsage]:
        """UTC application-subscription totals; actuals replace conservative liability.

        Identity is selected only by the authenticated actor, never by query parameters.
        Only durable usage events are counted; validation/configuration failures without
        such an event remain observable through telemetry, not this ledger report.
        """
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        return await CallerUsageService(get_engine().repository).summarize(
            period, actor.tenant_id, actor.principal_id, "RateLimit.Admin" in actor.roles
        )

    async def reader_assignments(actor: Identity) -> list[Assignment]:
        assignments: list[Assignment] = []
        for record in await get_engine().configuration("assignments"):
            try:
                assignment = Assignment.model_validate(record)
            except ValidationError:
                # Legacy principal-scoped assignments are not app access grants.
                continue
            if (
                assignment.tenant_id == actor.tenant_id
                and actor.principal_id in assignment.reader_principal_ids
            ):
                assignments.append(assignment)
        return assignments

    @app.get("/api/subscriptions")
    async def subscriptions(actor: Auth) -> list[Record]:
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        allowed = None
        if "RateLimit.Admin" not in actor.roles:
            allowed = {
                (assignment.tenant_id, assignment.subscription_id)
                for assignment in await reader_assignments(actor)
            }
        return [
            {
                "id": subscription_id,
                "tenant_id": application.tenant_id,
                "display_name": application.display_name,
            }
            for subscription_id, application in sorted(config.application_registry.items())
            if allowed is None or (application.tenant_id, subscription_id) in allowed
        ]

    @app.get("/api/{collection}")
    async def listing(collection: str, actor: Auth) -> list[Record]:
        if collection not in (
            "policies",
            "prices",
            "assignments",
            "usage",
            "audit",
            "reconciliation",
        ):
            raise HTTPException(404)
        actor.require("RateLimit.Admin", "RateLimit.Reader")
        service = get_engine()
        admin = "RateLimit.Admin" in actor.roles
        if collection in ("usage", "audit", "reconciliation"):
            return await service.report(collection, actor.tenant_id, actor.principal_id, admin)
        records = await service.configuration(collection)
        if admin:
            if collection in ("policies", "assignments"):
                return [
                    record
                    for record in records
                    if record.get("subscription_id") and "principal_id" not in record
                ]
            return records
        if collection == "prices":
            return records if admin or await reader_assignments(actor) else []
        visible_assignments = await reader_assignments(actor)
        if collection == "assignments":
            return [
                assignment.model_dump(mode="json", exclude_none=True)
                for assignment in visible_assignments
            ]
        assignments = []
        for raw in await service.configuration("assignments"):
            try:
                assignments.append(Assignment.model_validate(raw))
            except ValidationError:
                continue
        bound = {p for a in assignments for p in a.policy_ids}
        assigned = {p for a in visible_assignments for p in a.policy_ids}
        subscriptions = {a.subscription_id for a in visible_assignments}
        policies: list[Policy] = []
        for raw in records:
            try:
                policies.append(Policy.model_validate(raw))
            except ValidationError:
                # Legacy principal-scoped policies are deliberately not widened.
                continue
        return [
            policy.model_dump(mode="json")
            for policy in policies
            if policy.tenant_id in ("*", actor.tenant_id)
            and any(
                policy.subscription_id in ("*", subscription_id)
                for subscription_id in subscriptions
            )
            and (policy.id not in bound or policy.id in assigned)
        ]

    models: dict[str, type[Contract]] = {
        "policies": Policy,
        "prices": Price,
        "assignments": Assignment,
    }

    async def save(collection: str, record_id: str, body: Contract, actor: Identity) -> Record:
        actor.require("RateLimit.Admin")
        record = body.model_dump(mode="json")
        if isinstance(body, Assignment) and body.display_label is None:
            record.pop("display_label")
        if record["id"] != record_id:
            raise HTTPException(400, "Path ID must match body ID")
        audit = event(
            "configuration",
            uuid4().hex,
            actor.tenant_id,
            actor.principal_id,
            {
                "action": "put",
                "collection": collection,
                "record_id": record_id,
                "actor_id": actor.principal_id,
                "record": record,
            },
        )
        await get_engine().repository.mutate(collection, record_id, record, audit)
        emit("configuration_written", action="put", collection=collection, status="ok")
        return record

    @app.put("/api/policies/{record_id}")
    async def put_policy(record_id: str, body: Policy, actor: Auth) -> Record:
        return await save("policies", record_id, body, actor)

    @app.put("/api/prices/{record_id}")
    async def put_price(record_id: str, body: Price, actor: Auth) -> Record:
        return await save("prices", record_id, body, actor)

    @app.put("/api/assignments/{record_id}")
    async def put_assignment(record_id: str, body: Assignment, actor: Auth) -> Record:
        return await save("assignments", record_id, body, actor)

    @app.delete("/api/{collection}/{record_id}")
    async def delete(collection: str, record_id: str, actor: Auth) -> Record:
        actor.require("RateLimit.Admin")
        if collection not in models:
            raise HTTPException(404)
        audit = event(
            "configuration",
            uuid4().hex,
            actor.tenant_id,
            actor.principal_id,
            {
                "action": "delete",
                "collection": collection,
                "record_id": record_id,
                "actor_id": actor.principal_id,
            },
        )
        await get_engine().repository.mutate(collection, record_id, None, audit)
        emit("configuration_written", action="delete", collection=collection, status="ok")
        return {"deleted": record_id}

    return app
