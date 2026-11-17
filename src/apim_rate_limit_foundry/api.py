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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from azure.core.exceptions import AzureError, ServiceResponseTimeoutError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from apim_rate_limit_foundry.api_errors import register_error_handlers
from apim_rate_limit_foundry.api_services import ApiServices
from apim_rate_limit_foundry.auth import (
    ROLE_ADMIN,
    ROLE_GATEWAY,
    ROLE_READER,
    Identity,
    authenticate,
)
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import CONFIG_MODELS, GatewayServices
from apim_rate_limit_foundry.engine.chargeback_aggregator import DIMENSION_FIELDS
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.models.responses import (
    BudgetDecision,
    BudgetStatus,
    ChargebackRow,
    ConfigRecord,
    DashboardTile,
    DeletedRecord,
    Health,
    ModelInfo,
    UsageEvent,
    UsageRecordResult,
)
from apim_rate_limit_foundry.reports.dashboard import DashboardPeriod, DashboardService
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.stores.contracts import Record
from apim_rate_limit_foundry.telemetry import emit

MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
CHARGEBACK_FIELDS = [
    *DIMENSION_FIELDS,
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_micro_usd",
    "unknown_requests",
    "cache_write_tokens",
    "cost_basis",
]

router = APIRouter(prefix="/api")


def get_services(request: Request) -> ApiServices:
    """Resolve the application's lazily built clients."""
    return request.app.state.services


Services = Annotated[ApiServices, Depends(get_services)]


def get_gateway(services: Services) -> GatewayServices:
    """Resolve the budget services, building cloud clients on first use."""
    return services.gateway


def get_identity(request: Request, services: Services) -> Identity:
    """Authenticate the platform-validated caller; raises 401 when it cannot be trusted."""
    return authenticate(request, services.settings)


Gateway = Annotated[GatewayServices, Depends(get_gateway)]
Actor = Annotated[Identity, Depends(get_identity)]


def require_collection(collection: str) -> None:
    """Reject collection names outside the configuration catalog with HTTP 404."""
    if collection not in CONFIG_MODELS:
        raise HTTPException(404)


def require_month(month: str) -> None:
    """Reject anything but ``YYYY-MM`` with HTTP 400."""
    if MONTH_PATTERN.fullmatch(month) is None:
        raise HTTPException(400, "Month must use YYYY-MM")


def chargeback_csv(rows: list[Record], month: str) -> Response:
    """Render rows with a fixed column order as a downloadable attachment."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CHARGEBACK_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="chargeback-{month}.csv"'},
    )


@router.get("/health", response_model=Health)
async def health(services: Services) -> Record:
    """Return status and Azure cloud selection, without probing dependencies.

    This is process health, not proof that Redis, Table or the provider works;
    deployed platform authentication still applies before this route is reached.
    """
    return {"status": "ok", "cloud": services.settings.azure_cloud}


@router.get("/dashboard", response_model=list[DashboardTile])
async def dashboard_tiles(
    request: Request, actor: Actor, services: Services, period: DashboardPeriod = "24h"
) -> list[Record]:
    """Return fixed deployed dashboard tiles for an administrator.

    The only query parameter is one period: ``1h``, ``24h`` (default) or ``7d``.
    HTTP 200 contains tile metadata, columns, rows, truncation and per-tile
    errors; unavailable tiles must not be interpreted as zero activity.
    Invalid query keys yield 400; unavailable dashboard configuration or a
    failed overall fetch yields 503; a query or overall deadline timeout yields
    504. Arbitrary KQL/workspace input is rejected.
    """
    actor.require(ROLE_ADMIN)
    if set(request.query_params) - {"period"} or len(request.query_params.getlist("period")) > 1:
        raise HTTPException(400, "Only a single dashboard period is accepted")
    service: DashboardService | None = services.dashboard
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


@router.post("/budgets/check", response_model=BudgetDecision)
async def check_budget(body: BudgetCheck, actor: Actor, gateway: Gateway) -> Record:
    """Evaluate an authenticated gateway's request without waiting for Table.

    JSON supplies request/tenant/principal/subscription IDs, a model alias,
    API protocol and streaming flag. HTTP 200 returns request_id, allowed,
    reason, denied_budget_ids, reset_at and retry_after; a monthly denial is
    still a successful decision here, which APIM translates into HTTP 429.
    Request-ID conflicts yield 409; unavailable operational state yields 503.
    Admission checks current spend, not a reservation for future token cost.
    """
    actor.require(ROLE_GATEWAY)
    return await gateway.admission.check(body)


@router.post("/usage/record", response_model=UsageRecordResult, response_model_exclude_unset=True)
async def record_usage(body: UsageRecordRequest, actor: Actor, gateway: Gateway) -> Record:
    """Finalize gateway usage in Redis and schedule its best-effort mirror.

    JSON supplies request_id, status and the original provider_usage object
    for actual usage. HTTP 200 returns ``event`` and ``replayed``; it confirms
    Redis accounting, not durable Table persistence or Event Hub delivery.
    Unknown usage remains unpriced. Conflicting replay/context yields 409.
    """
    actor.require(ROLE_GATEWAY)
    return await gateway.usage.record(body)


@router.get("/models", response_model=list[ModelInfo])
async def registered_models(actor: Actor, services: Services, gateway: Gateway) -> list[Record]:
    """List protocol/alias IDs, deployments, price versions and token bounds.

    Admins see the registry; readers need an enabled assignment or receive
    an empty list. Provider credentials and endpoints are never returned.
    """
    actor.require(ROLE_ADMIN, ROLE_READER)
    if not actor.is_admin and not await gateway.admission.has_assignment(
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
        for key, deployment in sorted(services.settings.model_registry.items())
    ]


@router.get("/usage", response_model=list[UsageEvent], response_model_exclude_unset=True)
async def usage(actor: Actor, gateway: Gateway, month: str | None = None) -> list[Record]:
    """Return eventually persisted tenant usage for ``month=YYYY-MM`` (default: current).

    Restricted to the caller's own events for readers. Invalid month syntax
    yields 400.
    """
    actor.require(ROLE_ADMIN, ROLE_READER)
    if month is not None:
        require_month(month)
    return await gateway.reports.usage(actor.tenant_id, actor.principal_id, actor.is_admin, month)


@router.get("/budgets/status", response_model=list[BudgetStatus])
async def budget_status(actor: Actor, gateway: Gateway) -> list[Record]:
    """Return applicable live Redis totals, limits and remaining micro-USD.

    Admins see tenant budgets; readers see budgets applicable to themselves.
    These approximate operational totals may differ from durable usage reports.
    """
    actor.require(ROLE_ADMIN, ROLE_READER)
    return await gateway.reports.budget_status(actor.tenant_id, actor.principal_id, actor.is_admin)


@router.get("/chargeback", response_model=list[ChargebackRow], response_model_exclude_unset=True)
async def chargeback(
    actor: Actor,
    gateway: Gateway,
    month: str,
    output: Annotated[Literal["json", "csv"], Query(alias="format")] = "json",
) -> list[Record] | Response:
    """Aggregate durable usage for ``month=YYYY-MM`` as JSON or CSV.

    ``format`` defaults to JSON; CSV uses a fixed column order and attachment
    name. Admins see the tenant, readers only their own usage. Unknown usage
    contributes unknown_requests rather than fabricated zero-cost counters.
    Invalid month syntax yields 400; unsupported typed query values yield 422.
    """
    actor.require(ROLE_ADMIN, ROLE_READER)
    require_month(month)
    rows = await gateway.reports.chargeback(
        actor.tenant_id, month, None if actor.is_admin else actor.principal_id
    )
    return rows if output == "json" else chargeback_csv(rows, month)


@router.get("/{collection}", response_model=list[ConfigRecord], response_model_exclude_unset=True)
async def listing(collection: str, actor: Actor, gateway: Gateway) -> list[Record]:
    """Return tenant-scoped active configuration records to admins only.

    Supported collections are budgets, organizations, assignments and prices;
    unknown collection names return 404. Record schemas match the PUT bodies.
    """
    require_collection(collection)
    actor.require(ROLE_ADMIN)
    return [
        row
        for row in await gateway.configuration.list(collection)
        if row.get("tenant_id", actor.tenant_id) == actor.tenant_id
    ]


@router.put(
    "/{collection}/{record_id}", response_model=ConfigRecord, response_model_exclude_unset=True
)
async def save_configuration(
    collection: str, record_id: str, body: Record, actor: Actor, gateway: Gateway
) -> Record:
    """Validate and durably upsert one admin configuration record plus audit.

    The path identifies collection/record ID; JSON must satisfy that collection's
    schema and the authenticated tenant's relationships. The response is the
    saved record. Redis configuration is invalidated after the durable mutation;
    unlike admission/usage mirrors, this operation waits for its Table write.
    """
    actor.require(ROLE_ADMIN)
    require_collection(collection)
    result = await gateway.configuration.save(
        collection, record_id, body, actor.tenant_id, actor.principal_id
    )
    emit("configuration_written", action="put", collection=collection, status="ok")
    return result


@router.delete("/{collection}/{record_id}", response_model=DeletedRecord)
async def delete_configuration(
    collection: str, record_id: str, actor: Actor, gateway: Gateway
) -> Record:
    """Tombstone an admin record and return ``{"deleted": record_id}``.

    Relationship checks prevent deleting referenced organizations. The durable
    mutation/audit completes before Redis invalidation; usage history is retained.
    """
    actor.require(ROLE_ADMIN)
    require_collection(collection)
    await gateway.configuration.delete(collection, record_id, actor.tenant_id, actor.principal_id)
    emit("configuration_written", action="delete", collection=collection, status="ok")
    return {"deleted": record_id}


def create_app(
    settings: Settings | None = None,
    gateway: GatewayServices | None = None,
    dashboard: DashboardService | None = None,
) -> FastAPI:
    """Build the API, optionally injecting services/dashboard for isolated tests.

    Pydantic validates typed request bodies before a handler runs (HTTP 422);
    domain validation, conflicts and dependency failures map to 400, 409 and 503.
    """
    services = ApiServices(settings or Settings(), gateway, dashboard)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await services.close()

    app = FastAPI(title="AI Monthly Budget Gateway", lifespan=lifespan)
    app.state.services = services
    app.add_middleware(RequestTelemetryMiddleware)
    register_error_handlers(app)
    app.include_router(router)
    return app
