import asyncio
import json
import logging
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import SecretStr
from redis.exceptions import ResponseError

from apim_rate_limit_foundry import monitoring, telemetry
from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Reserve, Settle, Usage
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository
from tests.test_api import ADMIN, GATEWAY


@pytest.fixture
def domain_logs(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger(telemetry.LOGGER_NAME)
    logger.addHandler(caplog.handler)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(original_level)


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    try:
        yield exporter
    finally:
        provider.shutdown()


def log_attributes(logs: pytest.LogCaptureFixture, event: str) -> list[dict]:
    return [
        telemetry.safe_attributes(record.__dict__)
        for record in logs.records
        if record.getMessage() == event
    ]


def test_exporter_initialization_is_explicit_once_and_safe(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = MagicMock()
    register = MagicMock()
    monkeypatch.setattr(monitoring, "configure_azure_monitor", configure)
    monkeypatch.setattr(monitoring.atexit, "register", register)
    monkeypatch.setattr(monitoring, "_initialized", False)
    monitoring.configure_monitoring(settings)
    monitoring.configure_monitoring(settings.model_copy(update={"telemetry_enabled": False}))
    configure.assert_not_called()
    production = settings.model_copy(
        update={
            "applicationinsights_connection_string": SecretStr("secret-connection"),
            "telemetry_enabled": True,
            "otel_traces_sampler_arg": 0.25,
        }
    )
    monitoring.configure_monitoring(production)
    monitoring.configure_monitoring(production)
    configure.assert_called_once()
    options = configure.call_args.kwargs
    assert options["logger_name"] == telemetry.LOGGER_NAME
    assert options["connection_string"] == "secret-connection"
    assert options["resource"].attributes["service.name"] == "rate-limiter"
    assert options["sampling_ratio"] == 0.25
    assert options["disable_offline_storage"] is True
    assert options["disable_metrics"] is True
    assert options["enable_trace_based_sampling_for_logs"] is False
    assert all(not option["enabled"] for option in options["instrumentation_options"].values())
    assert "httpx2" in options["instrumentation_options"]
    register.assert_called_once_with(monitoring.flush_telemetry)
    assert (
        logging.getLogger("azure.core.pipeline.policies.http_logging_policy").level
        == logging.WARNING
    )


def test_shutdown_flush_is_bounded_and_not_part_of_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer, logs = MagicMock(), MagicMock()
    monkeypatch.setattr(monitoring.trace, "get_tracer_provider", lambda: tracer)
    monkeypatch.setattr(monitoring, "get_logger_provider", lambda: logs)
    monitoring.flush_telemetry()
    tracer.force_flush.assert_called_once_with(timeout_millis=5000)
    logs.force_flush.assert_called_once_with(timeout_millis=5000)


def test_safety_filter_sanitizes_exported_attributes_and_exception_text() -> None:
    error = OSError("https://secret.example?token=secret")
    record = logging.LogRecord(
        telemetry.LOGGER_NAME,
        logging.ERROR,
        "",
        0,
        "unsafe %s",
        ("token-secret",),
        (type(error), error, None),
    )
    record.__dict__.update(
        tenant_id="raw-tenant",
        principal_id="raw-principal",
        prompt="private-prompt",
        token="secret",
        key="redis-key",
        body={"data": "private"},
        correlation_id="safe-id",
        model="model?token=secret",
        matched_policy_ids=["policy-1", "bad\nid"],
        input_tokens=9,
        unknown="private",
    )
    assert telemetry.SafeTelemetryFilter().filter(record)
    assert record.getMessage() == "application_event"
    assert record.exc_info is None
    assert record.args == ()
    assert telemetry.safe_attributes(record.__dict__) == {
        "correlation_id": "safe-id",
        "matched_policy_ids": ["policy-1"],
        "input_tokens": 9,
    }
    payload = telemetry.JsonFormatter().format(record)
    for secret in ("raw-tenant", "raw-principal", "private", "redis-key", "secret", '"token"'):
        assert secret not in payload
    assert "tenant_id" not in record.__dict__


async def test_decision_settlement_logs_show_accounting_without_internal_keys(
    engine: Engine,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    decision = await engine.reserve(request_body)
    replay = await engine.reserve(request_body)
    assert replay == decision
    for index in range(3):
        await engine.reserve(request_body.model_copy(update={"request_id": f"extra-{index}"}))
    events = log_attributes(domain_logs, "rate_decision")
    assert events[0]["remaining"] == 200
    assert events[0]["estimated"] is True
    assert events[0]["reserved_cost_micro_usd"] == events[0]["cost_micro_usd"] == 100
    assert events[1]["replayed"] is True
    assert events[-1]["allowed"] is False
    assert events[-1]["denied_policy_ids"] == ["policy-1"]
    assert events[-1]["reason"] == "budget_exhausted"
    assert events[-1]["reserved_cost_micro_usd"] == 100
    assert events[-1]["cost_micro_usd"] == 0
    assert events[-1]["service"] == "foundry"
    assert events[-1]["model"] == "model-1"
    assert events[-1]["api_protocol"] == "openai-chat"
    settlement = Settle(
        reservation_id=decision.reservation_id,
        status="actual",
        usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
    )
    await engine.settle(settlement)
    actual = log_attributes(domain_logs, "settlement_recorded")[-1]
    assert actual["cost_micro_usd"] == 18
    assert actual["cached_input_tokens"] == 4
    assert actual["cached_input_reported"] is True
    assert actual["estimated"] is False
    assert actual["price_version"] == "v1"
    assert actual["reserved_cost_micro_usd"] == 100
    assert actual["refunded_cost_micro_usd"] == 82
    assert log_attributes(domain_logs, "settlement_price")[-1]["cached_input_per_million"] == "0.5"
    assert log_attributes(domain_logs, "settlement_policy_debit")[-1]["amount"] == 18
    settled_policy = log_attributes(domain_logs, "settlement_policy_debit")[-1]
    assert settled_policy["reserved_amount"] == 100
    assert settled_policy["applied_amount"] == 18
    assert settled_policy["refunded_amount"] == 82
    assert settled_policy["api_protocol"] == "openai-chat"
    await engine.settle(settlement)
    with pytest.raises(Conflict):
        await engine.settle(settlement.model_copy(update={"status": "conservative"}))
    assert log_attributes(domain_logs, "operation_failed")[-1]["error_type"] == "Conflict"
    serialized = json.dumps([telemetry.safe_attributes(r.__dict__) for r in domain_logs.records])
    for sensitive in ("tenant-1", "user-1", '"key"', '"fingerprint"', '"request"'):
        assert sensitive not in serialized


async def test_conservative_settlement_logs_retained_maximum(
    engine: Engine,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    decision = await engine.reserve(request_body.model_copy(update={"streaming": True}))
    await engine.release(decision.reservation_id)
    result = log_attributes(domain_logs, "settlement_recorded")[-1]
    assert result["status"] == "conservative"
    assert result["estimated"] is True
    assert result["cost_micro_usd"] == 100
    assert result["input_tokens"] == 10 and result["output_tokens"] == 20
    assert result["refunded_cost_micro_usd"] == 0
    assert log_attributes(domain_logs, "settlement_policy_debit")[-1]["refunded_amount"] == 0
    assert list(engine.counters.counts.values()) == [100]


async def test_policy_traces_distinguish_binding_denial_from_unspent_demand(
    engine: Engine,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    await engine.repository.create(
        "policies",
        "requests-policy",
        {
            "id": "requests-policy",
            "name": "One request",
            "service": "foundry",
            "metric": "requests",
            "period": "day",
            "limit": 1,
        },
    )
    await engine.reserve(request_body)
    await engine.reserve(request_body)
    denied = await engine.reserve(request_body.model_copy(update={"request_id": "denied"}))
    assert denied.allowed is False
    assert denied.denied_policy_ids == ["requests-policy"]
    charges = log_attributes(domain_logs, "reservation_policy_debit")
    assert charges[0]["policy_outcome"] == "allowed"
    assert charges[0]["applied_amount"] == charges[0]["amount"]
    assert charges[2]["replayed"] is True
    final = {item["policy_id"]: item for item in charges[-2:]}
    assert final["requests-policy"]["policy_outcome"] == "denied"
    assert final["policy-1"]["policy_outcome"] == "blocked"
    assert all(item["applied_amount"] == 0 for item in final.values())
    assert final["policy-1"]["amount"] == 100
    assert final["policy-1"]["remaining"] == 200


def test_custom_trace_schema_is_versioned_and_cannot_be_overridden(
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    telemetry.emit(
        "rate_decision",
        event_name="untrusted-name",
        event_version=900,
        allowed=False,
        tenant_id="private-tenant",
    )
    record = domain_logs.records[-1]
    assert record.getMessage() == "rate_decision"
    attributes = telemetry.safe_attributes(record.__dict__)
    assert attributes["event_name"] == "rate_decision"
    assert attributes["event_version"] == 1
    assert "tenant_id" not in record.__dict__


async def test_incomplete_provider_usage_logs_conservative_pending_without_metadata(
    engine: Engine,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    decision = await engine.reserve(request_body)
    await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            provider_usage={
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "prompt_tokens_details": {"audio_tokens": 1},
            },
        )
    )
    pending = log_attributes(domain_logs, "settlement_pending")[-1]
    assert pending["status"] == "conservative" and pending["estimated"]
    assert pending["reason"] == "incomplete_provider_usage"
    assert list(engine.counters.counts.values()) == [100]
    assert "audio_tokens" not in json.dumps(
        [telemetry.safe_attributes(r.__dict__) for r in domain_logs.records]
    )


@pytest.mark.parametrize(
    ("service", "metric", "price_field"),
    [
        ("language", "text_records", "per_text_record"),
        ("document-intelligence", "pages", "per_page"),
    ],
)
async def test_service_unit_settlement_and_operation_ownership_are_observable(
    service: str,
    metric: str,
    price_field: str,
    engine: Engine,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    await engine.repository.create(
        "prices",
        "units-price",
        {
            "id": "units-price",
            "service": service,
            "model": "units-model",
            "version": "units-v1",
            price_field: "0.01",
            "per_request": "0",
        },
    )
    await engine.repository.create(
        "policies",
        "units-policy",
        {
            "id": "units-policy",
            "name": "Unit limit",
            "service": service,
            "metric": metric,
            "period": "hour",
            "limit": 10,
        },
    )
    request = request_body.model_copy(
        update={
            "service": service,
            "model": "units-model",
            "usage": Usage(**{metric: 5}),
            "document_bound_verified": service == "document-intelligence",
        }
    )
    decision = await engine.reserve(request)
    await engine.settle(
        Settle(reservation_id=decision.reservation_id, status="actual", usage=Usage(**{metric: 2}))
    )
    actual = log_attributes(domain_logs, "settlement_recorded")[-1]
    assert actual[metric] == 2
    assert actual["service"] == service
    assert actual["cost_micro_usd"] == 20000
    if service == "document-intelligence":
        operation = {
            "operation_id": "private-operation",
            "tenant_id": request.tenant_id,
            "principal_id": request.principal_id,
            "model": request.model,
        }
        assert (
            await engine.bind_operation({**operation, "reservation_id": decision.reservation_id})
        )["allowed"]
        assert (await engine.check_operation(operation))["allowed"]
        assert not (await engine.check_operation({**operation, "principal_id": "other-user"}))[
            "allowed"
        ]
        ownership = log_attributes(domain_logs, "operation_ownership")
        assert [item["allowed"] for item in ownership] == [True, True, False]
        assert "private-operation" not in json.dumps(ownership)


async def test_http_correlation_trace_parent_and_safe_error_logs(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
    spans: InMemorySpanExporter,
) -> None:
    headers = {
        **GATEWAY,
        "X-Correlation-ID": "apim-safe-123",
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/decisions/reserve?token=secret-query",
            headers=headers,
            json=request_body.model_dump(mode="json"),
        )
        assert response.headers["X-Correlation-ID"] == "apim-safe-123"
        await client.post(
            "/api/decisions/settle",
            headers=headers,
            json={
                "reservation_id": response.json()["reservation_id"],
                "status": "conservative",
                "usage": {},
            },
        )
        engine.repository.fail = True
        failure = await client.post(
            "/api/decisions/reserve",
            headers=headers,
            json=request_body.model_dump(mode="json"),
        )
        assert failure.status_code == 503
        assert failure.headers["X-Correlation-ID"] == "apim-safe-123"
    assert log_attributes(domain_logs, "rate_decision")[0]["correlation_id"] == "apim-safe-123"
    assert (
        log_attributes(domain_logs, "settlement_recorded")[0]["correlation_id"] == "apim-safe-123"
    )
    requests = spans.get_finished_spans()
    assert len(requests) == 3
    assert requests[0].context.trace_id == int("0123456789abcdef0123456789abcdef", 16)
    assert requests[0].parent.span_id == int("0123456789abcdef", 16)
    assert requests[-1].status.status_code == StatusCode.ERROR
    assert requests[0].attributes["route"] == "/api/decisions/reserve"
    assert requests[0].attributes["http.request.method"] == "POST"
    assert requests[0].attributes["http.route"] == "/api/decisions/reserve"
    assert requests[0].attributes["http.response.status_code"] == 200
    assert requests[-1].attributes["http.response.status_code"] == 503
    assert telemetry.correlation_id.get() == ""
    assert "secret-query" not in repr(requests)
    assert "secret-query" not in domain_logs.text


@pytest.mark.parametrize("incoming", ["", "x" * 129, "unsafe/id", "unsafe?token=secret"])
async def test_invalid_correlation_is_replaced_and_echoed(
    incoming: str,
    engine: Engine,
    settings: Settings,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/health", headers={"X-Correlation-ID": incoming})
    identifier = response.headers["X-Correlation-ID"]
    assert telemetry.safe_id(identifier)
    assert len(identifier) == 32
    assert identifier != incoming


async def test_functions_asgi_tracing_context_is_used_when_header_absent(
    engine: Engine,
    settings: Settings,
    spans: InMemorySpanExporter,
) -> None:
    app = create_app(settings, engine)
    original = app

    async def adapter(scope, receive, send):
        scope["azure_functions.trace_context"] = SimpleNamespace(
            trace_parent="00-11111111111111111111111111111111-2222222222222222-01",
        )
        await original(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=adapter),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
    request = spans.get_finished_spans()[0]
    assert request.context.trace_id == int("1" * 32, 16)
    assert request.parent.span_id == int("2" * 16, 16)


async def test_parallel_requests_do_not_share_correlation_context(
    engine: Engine,
    settings: Settings,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        responses = await asyncio.gather(
            *(
                client.get("/api/health", headers={"X-Correlation-ID": f"parallel-{n}"})
                for n in range(5)
            )
        )
    assert [response.headers["X-Correlation-ID"] for response in responses] == [
        f"parallel-{n}" for n in range(5)
    ]
    assert {r["correlation_id"] for r in log_attributes(domain_logs, "request_completed")} == {
        f"parallel-{n}" for n in range(5)
    }
    assert telemetry.correlation_id.get() == ""


async def test_unexpected_failure_retains_correlation_and_does_not_expose_message(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    engine.repository.get = AsyncMock(side_effect=RuntimeError("private-token"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/decisions/reserve",
            headers={**GATEWAY, "X-Correlation-ID": "safe-error-id"},
            json=request_body.model_dump(mode="json"),
        )
    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "safe-error-id"
    assert "private-token" not in response.text
    assert "private-token" not in domain_logs.text
    assert log_attributes(domain_logs, "request_failed")[-1]["error_type"] == "RuntimeError"


async def test_dependency_spans_include_status_and_duration_never_values(
    settings: Settings,
    domain_logs: pytest.LogCaptureFixture,
    spans: InMemorySpanExporter,
) -> None:
    table = AsyncMock()
    table.get_entity.return_value = {"payload": '{"id":"private-record"}'}
    repository = TableRepository(table)
    assert await repository.get("policies", "private-key") == {"id": "private-record"}
    table.get_entity.side_effect = OSError("private-token private-tenant private-principal")
    with pytest.raises(OSError, match="private-token"):
        await repository.get("policies", "private-key")
    client = AsyncMock()
    client.eval.return_value = '{"allowed":true}'
    counters = RedisCounters(settings, None, client)
    assert (await counters.reserve("private-id", "private-fingerprint", [], {}))["allowed"]
    client.eval.side_effect = ResponseError("CONFLICT private-token")
    with pytest.raises(Conflict):
        await counters.finalize("private-id", [], "private-fingerprint")
    finished = spans.get_finished_spans()
    assert [span.name for span in finished] == [
        "table.get",
        "table.get",
        "redis.reserve",
        "redis.finalize",
    ]
    assert [span.status.status_code for span in finished] == [
        StatusCode.OK,
        StatusCode.ERROR,
        StatusCode.OK,
        StatusCode.ERROR,
    ]
    assert all(not span.events for span in finished)
    dependencies = log_attributes(domain_logs, "dependency_completed")
    assert all(event["duration_ms"] >= 0 for event in dependencies)
    assert dependencies[-1]["error_type"] == "Conflict"
    assert "private-" not in repr(finished) + json.dumps(dependencies)


async def test_configuration_and_recovery_events_do_not_export_records_or_identity(
    engine: Engine,
    settings: Settings,
    domain_logs: pytest.LogCaptureFixture,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        response = await client.put(
            "/api/assignments/private-record",
            headers=ADMIN,
            json={
                "id": "private-record",
                "tenant_id": "private-tenant",
                "principal_id": "private-principal",
                "policy_ids": ["policy-1"],
            },
        )
        assert response.status_code == 200
        assert (
            await client.delete("/api/assignments/private-record", headers=ADMIN)
        ).status_code == 200
    await engine.recover()
    writes = log_attributes(domain_logs, "configuration_written")
    assert [item["action"] for item in writes] == ["put", "delete"]
    assert log_attributes(domain_logs, "recovery_completed")[-1]["records"] == 0
    assert "private-" not in json.dumps(
        [telemetry.safe_attributes(r.__dict__) for r in domain_logs.records]
    )


async def test_timer_trace_and_error_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    domain_logs: pytest.LogCaptureFixture,
    spans: InMemorySpanExporter,
) -> None:
    monkeypatch.setattr("apim_rate_limit_foundry.config.Settings", lambda: settings)
    namespace = runpy.run_path("function_app.py")
    engine = SimpleNamespace(reconcile=AsyncMock(return_value=2))
    namespace["api"].state.get_engine = lambda: engine
    timer = SimpleNamespace(past_due=True)
    invocation = SimpleNamespace(
        invocation_id="safe-timer-id",
        trace_context=SimpleNamespace(
            trace_parent="00-11111111111111111111111111111111-2222222222222222-01",
        ),
    )
    function = namespace["reconcile_usage"].build().get_user_function()
    await function(timer, invocation)
    assert log_attributes(domain_logs, "reconciliation_timer_completed")[0]["records"] == 2
    engine.reconcile.side_effect = OSError("private-token")
    with pytest.raises(OSError):
        await function(timer, invocation)
    assert spans.get_finished_spans()[-1].status.status_code == StatusCode.ERROR
    assert "private-token" not in domain_logs.text
    assert telemetry.correlation_id.get() == ""
