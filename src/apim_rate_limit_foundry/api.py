import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
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
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict, Record, RecoveryRequired
from apim_rate_limit_foundry.telemetry import emit


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    config = settings or Settings()
    runtime: Runtime | None = None

    def get_engine() -> Engine:
        nonlocal runtime
        if engine is not None:
            return engine
        if runtime is None:
            runtime = Runtime(config)
        return runtime.engine

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
        if admin or collection == "prices":
            return records
        if collection == "assignments":
            return [
                r
                for r in records
                if r["tenant_id"] == actor.tenant_id and r["principal_id"] == actor.principal_id
            ]
        assignments = [
            Assignment.model_validate(a) for a in await service.configuration("assignments")
        ]
        bound = {p for a in assignments for p in a.policy_ids}
        assigned = {
            p
            for a in assignments
            if a.tenant_id == actor.tenant_id and a.principal_id == actor.principal_id
            for p in a.policy_ids
        }
        return [
            r
            for r in records
            if r.get("tenant_id", "*") in ("*", actor.tenant_id)
            and r.get("principal_id", "*") in ("*", actor.principal_id)
            and (r["id"] not in bound or r["id"] in assigned)
        ]

    models: dict[str, type[Contract]] = {
        "policies": Policy,
        "prices": Price,
        "assignments": Assignment,
    }

    async def save(collection: str, record_id: str, body: Contract, actor: Identity) -> Record:
        actor.require("RateLimit.Admin")
        record = body.model_dump(mode="json")
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
