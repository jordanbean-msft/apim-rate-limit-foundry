import asyncio
import json
import logging
from collections.abc import Iterator
from logging.handlers import BufferingHandler
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from azure.core.credentials import AccessToken, AccessTokenInfo
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError, HttpResponseError
from azure.monitor.query import LogsQueryResult, LogsTable
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import SecretStr
from redis.exceptions import RedisError
from starlette.requests import Request
from starlette.responses import StreamingResponse

from apim_rate_limit_foundry import monitoring
from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.rate_limit_metrics import RateLimitMetrics
from apim_rate_limit_foundry.reports.dashboard import DashboardService
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.streaming.request_telemetry import trace_stream_request
from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    JsonFormatter,
    correlation_id,
    outgoing_trace_headers,
    request_trace_context,
)
from tests.fakes import FakeHttpSession, persisted_usage

# Host-wide default ceilings (131072 input, 32768 output) at the fixture's 2/4 USD per million.
UNKNOWN_UPPER_BOUND = 131072 * 2 + 32768 * 4
TRACE_ID = "12345678901234567890123456789012"
TRACEPARENT = f"00-{TRACE_ID}-1234567890123456-01"
GATEWAY = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "gateway",
    "X-Local-Roles": "RateLimit.Gateway",
    "X-Correlation-ID": "inference-1",
    "traceparent": TRACEPARENT,
}


@pytest.fixture
def capture(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[SimpleNamespace]:
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    metrics = RateLimitMetrics(meter_provider.get_meter("test"))
    for module in (
        "background_writer",
        "engine.admission_telemetry",
        "engine.budget_status_reporter",
        "engine.usage_telemetry",
        "request_telemetry",
        "streaming.relay",
    ):
        monkeypatch.setattr(f"apim_rate_limit_foundry.{module}.rate_metrics", metrics)
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", tracer_provider.get_tracer)
    logger = logging.getLogger(LOGGER_NAME)
    previous_propagate = logger.propagate
    logger.propagate = False
    handler = BufferingHandler(10_000)
    logger.addHandler(handler)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    try:
        yield SimpleNamespace(reader=reader, metrics=metrics, spans=exporter, logs=handler.buffer)
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous_propagate
        tracer_provider.shutdown()
        meter_provider.shutdown()


def _check(request_id: str) -> BudgetCheck:
    return BudgetCheck(
        request_id=request_id,
        tenant_id="tenant-1",
        principal_id="user-1",
        subscription_id="application",
        model="model-1",
        api_protocol="openai-chat",
        streaming=False,
    )


def _points(capture: SimpleNamespace, name: str) -> list:
    data = capture.reader.get_metrics_data()
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


async def test_decisions_budget_snapshots_replays_and_disjoint_actual_metrics(
    gateway: GatewayServices, capture: SimpleNamespace
) -> None:
    await gateway.admission.check(_check("actual"))
    await gateway.admission.check(_check("actual"))
    await gateway.admission.check(_check("unknown"))
    actual = UsageRecordRequest(
        request_id="actual",
        status="actual",
        provider_usage={
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 60},
            "completion_tokens": 20,
        },
    )
    await asyncio.gather(gateway.usage.record(actual), gateway.usage.record(actual))
    await gateway.usage.record(UsageRecordRequest(request_id="unknown", status="usage_unknown"))
    assert not (await gateway.admission.check(_check("denied")))["allowed"]

    decisions = [r for r in capture.logs if r.msg == "budget_decision"]
    assert len(decisions) == 4
    assert decisions[1].replayed is True
    assert decisions[-1].denied_budget_count == 3
    assert all(r.request_id and r.api_protocol == "openai-chat" for r in decisions)
    budgets = [r for r in capture.logs if r.msg == "budget_evaluated"]
    assert len(budgets) == 9
    assert all(
        r.spent_micro_usd == 190 + UNKNOWN_UPPER_BOUND and r.remaining_micro_usd == 0
        for r in budgets[-3:]
    )
    assert {r.subject_type for r in budgets[-3:]} == {"user", "team", "department"}
    usage = [r for r in capture.logs if r.msg == "usage_recorded"]
    actual_log = next(r for r in usage if r.status == "actual")
    assert actual_log.uncached_input_tokens == 40
    assert actual_log.cached_input_tokens == 60
    assert actual_log.total_tokens == 120
    assert actual_log.cache_hit is True
    assert len([r for r in capture.logs if r.msg == "usage_record_replayed"]) == 1
    assert {
        p.attributes["token_type"]: p.value for p in _points(capture, "limiter.usage.tokens")
    } == {"uncached_input": 40, "cached_input": 60, "cache_write_input": 0, "output": 20}
    assert {
        p.attributes["cost_basis"]: p.value for p in _points(capture, "limiter.usage.cost")
    } == {"provider_usage": 190, "estimated_upper_bound": UNKNOWN_UPPER_BOUND}
    assert sum(p.value for p in _points(capture, "limiter.usage.records")) == 3
    for name in ("limiter.budget.decisions", "limiter.usage.records", "limiter.usage.tokens"):
        assert all(
            not ({"request_id", "user_ref", "budget_id", "subscription_id"} & p.attributes.keys())
            for p in _points(capture, name)
        )


async def test_accepted_usage_reports_balances_and_budget_metrics_without_identifiers(
    gateway: GatewayServices, capture: SimpleNamespace
) -> None:
    await gateway.admission.check(_check("actual"))
    await gateway.usage.record(
        UsageRecordRequest(
            request_id="actual",
            status="actual",
            provider_usage={"prompt_tokens": 100, "completion_tokens": 20},
        )
    )
    await gateway.admission.check(_check("denied"))
    await gateway.background.flush()

    statuses = [r for r in capture.logs if r.msg == "budget_status"]
    assert {r.subject_type for r in statuses} == {"user", "team", "department"}
    assert all(r.spent_micro_usd > 0 and r.team_id and r.department_id for r in statuses)
    assert all(r.user_ref for r in statuses if r.subject_type == "user")
    stages = {p.attributes["stage"] for p in _points(capture, "limiter.budget.utilization")}
    assert stages == {"admission", "usage"}
    assert sum(p.value for p in _points(capture, "limiter.budget.denials")) == 3
    writes = {p.attributes["outcome"] for p in _points(capture, "limiter.background.writes")}
    assert writes == {"completed"}
    for name in ("limiter.budget.utilization", "limiter.budget.denials"):
        assert all(
            not ({"budget_id", "user_ref", "request_id"} & p.attributes.keys())
            for p in _points(capture, name)
        )


@pytest.mark.parametrize(
    ("provider_usage", "reason"),
    [
        (None, "provider_usage_missing"),
        ({"prompt_tokens": "private-payload"}, "provider_usage_invalid"),
    ],
)
async def test_unknown_usage_is_explained_without_fabricated_tokens_or_cost(
    gateway: GatewayServices, capture: SimpleNamespace, provider_usage: dict | None, reason: str
) -> None:
    await gateway.admission.check(_check("unknown"))
    await gateway.usage.record(
        UsageRecordRequest(request_id="unknown", status="actual", provider_usage=provider_usage)
    )
    record = next(r for r in capture.logs if r.msg == "usage_recorded")
    assert record.status == "usage_unknown" and record.reason == reason
    assert not hasattr(record, "input_tokens")
    assert record.cost_micro_usd == UNKNOWN_UPPER_BOUND
    assert record.cost_basis == "estimated_upper_bound"
    assert not _points(capture, "limiter.usage.tokens")
    assert "private-payload" not in repr([r.__dict__ for r in capture.logs])


async def test_conflicts_and_metric_failures_do_not_change_accounting(
    gateway: GatewayServices, capture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.check(_check("duplicate"))
    other = _check("duplicate").model_copy(update={"model": "other"})
    with pytest.raises(Conflict):
        await gateway.admission.check(other)
    failure = next(r for r in capture.logs if r.msg == "operation_failed")
    assert failure.request_id == "duplicate" and failure.error_type == "Conflict"
    monkeypatch.setattr(
        capture.metrics.records, "add", Mock(side_effect=RuntimeError("private-export-error"))
    )
    result = await gateway.usage.record(
        UsageRecordRequest(request_id="duplicate", status="usage_unknown")
    )
    assert result["replayed"] is False
    await gateway.background.flush()
    assert len(await persisted_usage(gateway)) == 1
    assert any(r.msg == "metric_record_failed" for r in capture.logs)
    assert "private-export-error" not in repr([r.__dict__ for r in capture.logs])


async def test_http_and_domain_events_share_remote_trace_and_original_request_id(
    settings: Settings, gateway: GatewayServices, capture: SimpleNamespace
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, gateway)), base_url="http://test"
    ) as client:
        check = await client.post(
            "/api/budgets/check", json=_check("inference-1").model_dump(), headers=GATEWAY
        )
        recorded = await client.post(
            "/api/usage/record",
            json={"request_id": "inference-1", "status": "usage_unknown"},
            headers=GATEWAY,
        )
    assert check.status_code == recorded.status_code == 200
    assert (
        check.headers["X-Correlation-ID"] == recorded.headers["X-Correlation-ID"] == "inference-1"
    )
    records = [
        r
        for r in capture.logs
        if r.msg in ("request_completed", "budget_decision", "usage_recorded")
    ]
    assert {r.correlation_id for r in records} == {"inference-1"}
    assert {r.trace_id for r in records} == {TRACE_ID}
    spans = capture.spans.get_finished_spans()
    assert len({span.context.trace_id for span in spans}) == 1
    assert len({span.context.span_id for span in spans}) == len(spans)
    assert all(span.parent is not None for span in spans)
    assert len(_points(capture, "limiter.http.duration")) == 2
    assert correlation_id.get() == ""


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "expected"),
    [
        ("GET", "/api/health", {}, None, 200),
        ("GET", "/api/budgets", {}, None, 401),
        ("GET", "/api/budgets", GATEWAY, None, 403),
        ("POST", "/api/budgets/check", GATEWAY, {}, 422),
        ("GET", "/private-content?secret=private-query", {}, None, 404),
    ],
)
async def test_each_http_outcome_is_logged_without_raw_urls_or_bodies(
    settings: Settings,
    gateway: GatewayServices,
    capture: SimpleNamespace,
    method: str,
    path: str,
    headers: dict,
    body: dict | None,
    expected: int,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, gateway)), base_url="http://test"
    ) as client:
        response = await client.request(method, path, headers=headers, json=body)
    assert response.status_code == expected
    records = [r for r in capture.logs if r.msg == "request_completed"]
    assert len(records) == 1 and records[0].http_status == expected
    assert records[0].correlation_id == response.headers["X-Correlation-ID"]
    assert sum(p.value for p in _points(capture, "limiter.http.requests")) == 1
    serialized = repr([r.__dict__ for r in capture.logs])
    assert "private-content" not in serialized and "private-query" not in serialized


@pytest.mark.parametrize(
    ("error", "status"), [(TimeoutError("secret"), 503), (RuntimeError("secret"), 500)]
)
async def test_failed_calls_log_safe_error_type_and_correlated_completion(
    settings: Settings,
    gateway: GatewayServices,
    capture: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(gateway.repository, "list", AsyncMock(side_effect=error))
    headers = {**GATEWAY, "X-Local-Roles": "RateLimit.Admin"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(settings, gateway), raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/usage", headers=headers)
    assert response.status_code == status
    completed = next(r for r in capture.logs if r.msg == "request_completed")
    assert completed.status == "error" and completed.http_status == status
    assert completed.trace_id == TRACE_ID
    assert "secret" not in repr([r.__dict__ for r in capture.logs])
    assert all(not span.events for span in capture.spans.get_finished_spans())


async def test_stream_keeps_trace_through_iteration_provider_headers_and_finalization(
    capture: SimpleNamespace,
) -> None:
    observed = []

    @trace_stream_request
    async def handler(req: Request) -> StreamingResponse:
        async def chunks():
            observed.append(outgoing_trace_headers("inference-1"))
            yield b"first"
            observed.append(outgoing_trace_headers("inference-1"))

        return StreamingResponse(chunks())

    req = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/stream",
            "headers": [(k.lower().encode(), v.encode()) for k, v in GATEWAY.items()],
        }
    )
    response = await handler(req)
    assert not capture.spans.get_finished_spans()
    assert [chunk async for chunk in response.body_iterator] == [b"first"]
    assert len(capture.spans.get_finished_spans()) == 1
    assert all(h["traceparent"].split("-")[1] == TRACE_ID for h in observed)
    assert all(h["X-Correlation-ID"] == "inference-1" for h in observed)
    assert len([r for r in capture.logs if r.msg == "request_completed"]) == 1
    assert correlation_id.get() == ""


@pytest.mark.parametrize("completion", ["complete", "close", "cancel"])
async def test_real_stream_relay_links_provider_accounting_and_export_even_on_disconnect(
    gateway: GatewayServices,
    publisher: AsyncMock,
    settings: Settings,
    capture: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    completion: str,
) -> None:
    settings.model_registry = {
        "openai-chat:model-1": ModelDeployment(
            api_protocol="openai-chat",
            endpoint="https://models.example.com",
            path="/openai/deployments/model-1/chat/completions",
            model="model-1",
            audience="https://cognitiveservices.azure.com",
            api_version="2025-01-01-preview",
            price_version="v1",
            max_input_tokens=100,
            max_output_tokens=20,
        )
    }
    await gateway.admission.check(_check("inference-1").model_copy(update={"streaming": True}))
    capture.spans.clear()
    wire = {}

    async def chunks(size):
        yield b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n\n'
        yield b"data: [DONE]\n\n"

    provider_response = SimpleNamespace(
        status=200,
        headers={"Content-Type": "text/event-stream"},
        content=SimpleNamespace(iter_chunked=chunks),
        close=Mock(),
    )

    def post(url, **kwargs):
        wire["provider"] = kwargs["headers"]
        return provider_response

    credential = AsyncMock()
    credential.get_token.return_value.token = "not-logged"
    relay = StreamRelay(gateway, credential, settings, FakeHttpSession(post))

    @trace_stream_request
    async def handler(req: Request) -> StreamingResponse:
        status, content_type, body, headers = await relay.open(
            "tenant-1",
            "inference-1",
            json.dumps(
                {"model": "model-1", "stream": True, "stream_options": {"include_usage": True}}
            ).encode(),
        )
        return StreamingResponse(body, status_code=status, media_type=content_type, headers=headers)

    response = await handler(
        Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/stream",
                "headers": [(k.lower().encode(), v.encode()) for k, v in GATEWAY.items()],
            }
        )
    )
    iterator = response.body_iterator
    await anext(iterator)
    if completion == "complete":
        assert [chunk async for chunk in iterator] == [b"data: [DONE]\n\n"]
    elif completion == "close":
        await iterator.aclose()
    else:
        with pytest.raises(asyncio.CancelledError):
            await iterator.athrow(asyncio.CancelledError())

    await gateway.background.flush()
    records = await persisted_usage(gateway)
    assert len(records) == 1 and records[0]["data"]["status"] == "actual"
    event = publisher.publish.await_args.args[0]
    assert event["request_id"] == "inference-1"
    assert "trace_id" not in event and "traceparent" not in event
    assert wire["provider"]["X-Correlation-ID"] == "inference-1"
    spans = {span.name: span for span in capture.spans.get_finished_spans()}
    assert {
        "POST /api/stream",
        "provider.stream_open",
        "usage.record",
    } <= spans.keys()
    root = spans["POST /api/stream"]
    assert f"{root.context.trace_id:032x}" == TRACE_ID
    assert spans["provider.stream_open"].parent.span_id == root.context.span_id
    parts = wire["provider"]["traceparent"].split("-")
    assert (
        parts[1] == TRACE_ID and parts[2] == f"{spans['provider.stream_open'].context.span_id:016x}"
    )
    assert spans["usage.record"].parent.span_id == root.context.span_id
    identity_spans = [
        span
        for span in capture.spans.get_finished_spans()
        if span.name == "managed-identity.get_token"
    ]
    assert {span.parent.span_id for span in identity_spans} == {
        spans["provider.stream_open"].context.span_id
    }
    terminal = [r for r in capture.logs if r.msg == "request_completed"]
    assert len(terminal) == 1
    assert terminal[0].status == ("ok" if completion == "complete" else "error")
    assert correlation_id.get() == ""
    provider_response.close.assert_called_once()
    assert {p.attributes["outcome"] for p in _points(capture, "limiter.stream.outcomes")} == {
        "completed"
    }
    assert [p.attributes["http_status"] for p in _points(capture, "limiter.provider.duration")] == [
        200
    ]
    publisher.publish.assert_awaited_once()


async def test_concurrent_requests_cannot_leak_trace_or_correlation_context(
    capture: SimpleNamespace,
) -> None:
    async def app(scope, receive, send):
        await asyncio.sleep(0)
        scope["route"] = SimpleNamespace(path="/api/health")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=RequestTelemetryMiddleware(app)),
        base_url="http://test",
    ) as client:
        first, second = await asyncio.gather(
            client.get("/api/health", headers=GATEWAY),
            client.get(
                "/api/health",
                headers={
                    "X-Correlation-ID": "inference-2",
                    "traceparent": TRACEPARENT.replace(TRACE_ID, "a" * 32),
                },
            ),
        )
    assert first.headers["X-Correlation-ID"] == "inference-1"
    assert second.headers["X-Correlation-ID"] == "inference-2"
    completed = {r.correlation_id: r.trace_id for r in capture.logs if r.msg == "request_completed"}
    assert completed == {"inference-1": TRACE_ID, "inference-2": "a" * 32}
    assert correlation_id.get() == ""


def _assert_private_dependencies(capture: SimpleNamespace) -> None:
    spans = capture.spans.get_finished_spans()
    serialized = repr([dict(span.attributes) for span in spans]) + "".join(
        JsonFormatter().format(record) for record in capture.logs
    )
    assert "private-detail" not in serialized
    assert all(not span.events for span in spans)
    assert all(f"{span.context.trace_id:032x}" == TRACE_ID for span in spans)
    assert all(span.parent is not None for span in spans)
    assert trace.get_current_span().get_span_context().is_valid is False


async def test_dashboard_dependencies_and_partial_failures_keep_request_trace(
    settings: Settings, capture: SimpleNamespace
) -> None:
    service = DashboardService(settings, AsyncMock())
    service.arm = Mock()
    service.arm.send_request = AsyncMock(
        return_value=SimpleNamespace(status_code=200, text=lambda: "{}")
    )
    service._tiles = Mock(return_value=[{"id": "safe", "query": "private-detail"}] * 4)
    service.logs = Mock()
    service.logs.query_batch = AsyncMock(
        return_value=[
            LogsQueryResult(
                tables=[
                    LogsTable(
                        name="PrimaryResult",
                        columns=["Count"],
                        columns_types=["long"],
                        rows=[[1]],
                    )
                ]
            ),
            LogsQueryResult(tables=[]),
            SimpleNamespace(message="private-detail", code="private-detail"),
        ]
    )
    token = correlation_id.set("dashboard-request")
    try:
        with trace.get_tracer("test").start_as_current_span(
            "request", context=request_trace_context(TRACEPARENT)
        ):
            result = await service.fetch("1h")
    finally:
        correlation_id.reset(token)
    assert result[0]["rows"] == [[1]] and result[0]["error"] is None
    assert all(tile["error"] and tile["rows"] == [] for tile in result[1:])
    spans = {span.name: span for span in capture.spans.get_finished_spans()}
    arm, logs = spans["dashboard.read"], spans["dashboard.query_batch"]
    assert arm.attributes["peer.service"] == "azure-resource-manager"
    assert arm.attributes["http.request.method"] == "GET"
    assert arm.attributes["http.response.status_code"] == 200
    assert arm.status.status_code == StatusCode.OK
    assert logs.attributes["peer.service"] == "log-analytics"
    assert logs.attributes["http.request.method"] == "POST"
    assert logs.status.status_code == StatusCode.ERROR
    assert logs.attributes["error.type"] == "incomplete_query_results"
    failures = [r for r in capture.logs if r.msg == "dashboard_query_failed"]
    assert len(failures) == 3
    assert all(r.correlation_id == "dashboard-request" for r in failures)
    assert all(r.span_id == f"{logs.context.span_id:016x}" for r in failures)
    assert all(span.parent.span_id == spans["request"].context.span_id for span in (arm, logs))
    _assert_private_dependencies(capture)


async def test_dashboard_batch_exception_remains_best_effort(
    settings: Settings, capture: SimpleNamespace
) -> None:
    service = DashboardService(settings, AsyncMock())
    service.logs = Mock()
    error = HttpResponseError(message="private-detail")
    error.status_code = 429
    service.logs.query_batch = AsyncMock(side_effect=error)
    with trace.get_tracer("test").start_as_current_span(
        "request", context=request_trace_context(TRACEPARENT)
    ):
        result = await service._batch([{"query": "private-detail"}], "1h")
    assert result[0]["error"] and result[0]["rows"] == []
    span = capture.spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 429
    assert span.attributes["error.type"] == "HttpResponseError"
    failures = [r for r in capture.logs if r.msg == "dashboard_query_failed"]
    assert any(r.error_type == "HttpResponseError" and r.status == "unavailable" for r in failures)
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("transport_error", [False, True])
async def test_dashboard_arm_failure_keeps_status_and_propagates_unchanged(
    transport_error: bool, settings: Settings, capture: SimpleNamespace
) -> None:
    service = DashboardService(settings, AsyncMock())
    response = Mock(status_code=403, reason="private-detail", headers={})
    error = HttpResponseError(message="private-detail", response=response)
    service.arm = Mock(
        send_request=AsyncMock(
            return_value=response, side_effect=error if transport_error else None
        )
    )
    service.logs = Mock(query_batch=AsyncMock())
    with (
        trace.get_tracer("test").start_as_current_span(
            "request", context=request_trace_context(TRACEPARENT)
        ),
        pytest.raises(HttpResponseError) as raised,
    ):
        await service.fetch("1h")
    if transport_error:
        assert raised.value is error
    service.logs.query_batch.assert_not_awaited()
    span = capture.spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 403
    assert span.attributes["error.type"] == "HttpResponseError"
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("operation", ["arm", "logs"])
async def test_dashboard_dependency_cancellation_propagates(
    operation: str, settings: Settings, capture: SimpleNamespace
) -> None:
    service = DashboardService(settings, AsyncMock())
    error = asyncio.CancelledError("private-detail")
    service.arm = Mock(send_request=AsyncMock(side_effect=error))
    service.logs = Mock(query_batch=AsyncMock(side_effect=error))
    with (
        trace.get_tracer("test").start_as_current_span(
            "request",
            context=request_trace_context(TRACEPARENT),
            record_exception=False,
            set_status_on_exception=False,
        ),
        pytest.raises(asyncio.CancelledError) as raised,
    ):
        if operation == "arm":
            await service.fetch("1h")
        else:
            await service._batch([{"query": "private-detail"}], "1h")
    assert raised.value is error
    span = capture.spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "CancelledError"
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("failure", [False, True])
async def test_managed_identity_is_private_and_preserves_token_or_error(
    failure: bool, capture: SimpleNamespace
) -> None:
    credential = AsyncMock()
    error = AzureError("private-detail")
    token = AccessToken("private-detail", 9999999999)
    credential.get_token = AsyncMock(side_effect=error if failure else None, return_value=token)
    observed = ObservedCredential(credential)
    with trace.get_tracer("test").start_as_current_span(
        "request", context=request_trace_context(TRACEPARENT)
    ):
        if failure:
            with pytest.raises(AzureError) as raised:
                await observed.get_token("private-detail", claims="private-detail")
            assert raised.value is error
        else:
            assert await observed.get_token("private-detail", claims="private-detail") is token
    credential.get_token.assert_awaited_once_with("private-detail", claims="private-detail")
    span = capture.spans.get_finished_spans()[0]
    assert span.name == "managed-identity.get_token" and span.kind == SpanKind.CLIENT
    assert span.attributes["rpc.system"] == "azure.identity"
    assert "db.system" not in span.attributes
    assert span.status.status_code == (StatusCode.ERROR if failure else StatusCode.OK)
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("supports_info", [False, True])
async def test_managed_identity_preserves_sdk_refresh_metadata_and_fallback(
    supports_info: bool, capture: SimpleNamespace
) -> None:
    credential = AsyncMock(spec=None if supports_info else AsyncTokenCredential)
    token = AccessTokenInfo("private-detail", 9999999999, refresh_on=9999999000)
    credential.get_token.return_value = AccessToken(token.token, token.expires_on)
    if supports_info:
        credential.get_token_info.return_value = token
    observed = ObservedCredential(credential)
    with trace.get_tracer("test").start_as_current_span(
        "request", context=request_trace_context(TRACEPARENT)
    ):
        result = await observed.get_token_info(
            "private-detail", options={"claims": "private-detail", "enable_cae": True}
        )
    if supports_info:
        assert result is token and result.refresh_on == 9999999000
        credential.get_token_info.assert_awaited_once_with(
            "private-detail", options={"claims": "private-detail", "enable_cae": True}
        )
    else:
        assert result.token == token.token and result.expires_on == token.expires_on
        credential.get_token.assert_awaited_once_with(
            "private-detail", claims="private-detail", enable_cae=True
        )
    _assert_private_dependencies(capture)


async def test_redis_token_refresh_and_connections_are_correlated_without_credentials(
    settings: Settings, capture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = AsyncMock()
    credential.get_token.return_value = AccessToken("private-detail", 9999999999)
    first, second = Mock(aclose=AsyncMock()), Mock(aclose=AsyncMock())
    factory = Mock(side_effect=[first, second])
    monkeypatch.setattr("apim_rate_limit_foundry.stores.redis.Redis", factory)
    counters = RedisCounters(settings, credential)
    with trace.get_tracer("test").start_as_current_span(
        "request", context=request_trace_context(TRACEPARENT)
    ):
        assert await counters.connection() is first
        assert await counters.connection() is first
        counters.expires = 0
        assert await counters.connection() is second
    assert credential.get_token.await_count == 2
    first.aclose.assert_not_awaited()
    await counters.close()
    first.aclose.assert_awaited_once()
    second.aclose.assert_awaited_once()
    spans = capture.spans.get_finished_spans()
    connections = [span for span in spans if span.name == "redis.connection"]
    tokens = [span for span in spans if span.name == "managed-identity.get_token"]
    assert len(connections) == 2 and len(tokens) == 2
    assert all(token.parent.span_id in {s.context.span_id for s in connections} for token in tokens)
    assert all(span.attributes["db.system"] == "redis" for span in connections)
    _assert_private_dependencies(capture)


async def test_table_sdk_identity_is_a_child_of_the_existing_storage_dependency(
    capture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        table_endpoint="https://table.example.net",
        redis_host="redis.example.net",
        redis_username="function-identity",
    )
    credential = AsyncMock(spec=AsyncTokenCredential)
    credential.get_token.return_value = AccessToken("private-detail", 9999999999)
    monkeypatch.setattr(
        "apim_rate_limit_foundry.runtime.DefaultAzureCredential",
        Mock(return_value=credential),
    )

    def table_client(*args, **kwargs):
        async def get_entity(*args, **options):
            await kwargs["credential"].get_token("private-detail")
            return {"payload": '{"id":"safe"}'}

        return Mock(get_entity=AsyncMock(side_effect=get_entity), close=AsyncMock())

    monkeypatch.setattr("apim_rate_limit_foundry.runtime.TableClient", table_client)
    runtime = Runtime(settings)
    with trace.get_tracer("test").start_as_current_span(
        "request", context=request_trace_context(TRACEPARENT)
    ):
        assert await runtime.gateway.repository.get("organizations", "safe") == {"id": "safe"}
    await runtime.close()
    credential.close.assert_awaited_once()
    spans = {span.name: span for span in capture.spans.get_finished_spans()}
    storage, identity = spans["table.get"], spans["managed-identity.get_token"]
    assert identity.parent.span_id == storage.context.span_id
    assert storage.attributes["db.system"] == "azure.table"
    assert identity.status.status_code == StatusCode.OK
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("outcome", ["cancelled", "unavailable"])
async def test_redis_lookup_dependencies_preserve_cancellation_and_errors(
    outcome: str, settings: Settings, capture: SimpleNamespace
) -> None:
    error = (
        asyncio.CancelledError("private-detail")
        if outcome == "cancelled"
        else RedisError("private-detail")
    )
    client = Mock(get=AsyncMock(side_effect=error))
    counters = RedisCounters(settings, None, client)
    with (
        trace.get_tracer("test").start_as_current_span(
            "request",
            context=request_trace_context(TRACEPARENT),
            record_exception=False,
            set_status_on_exception=False,
        ),
        pytest.raises(type(error)),
    ):
        await counters.request("safe-id")
    spans = {span.name: span for span in capture.spans.get_finished_spans()}
    assert spans["redis.request"].status.status_code == StatusCode.ERROR
    client.lock.assert_not_called()
    _assert_private_dependencies(capture)


@pytest.mark.parametrize("parent", ["private-header", "00-" + "0" * 32 + "-1234567890123456-01"])
async def test_invalid_headers_use_host_trace_context_and_a_safe_response_id(
    capture: SimpleNamespace,
    parent: str,
) -> None:
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def app(scope, receive, send):
        scope["azure_functions.trace_context"] = SimpleNamespace(trace_parent=TRACEPARENT)
        await RequestTelemetryMiddleware(inner)(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/",
            headers={
                "traceparent": parent,
                "X-Correlation-ID": "@private-header",
            },
        )
    assert response.status_code == 200
    assert len(response.headers["X-Correlation-ID"]) == 32
    assert {r.trace_id for r in capture.logs} == {TRACE_ID}
    assert "private-header" not in repr([r.__dict__ for r in capture.logs])


async def test_post_header_cancellation_is_failed_and_context_is_restored(
    capture: SimpleNamespace,
) -> None:
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=RequestTelemetryMiddleware(app)),
        base_url="http://test",
    ) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get("/", headers=GATEWAY)
    completed = next(r for r in capture.logs if r.msg == "request_completed")
    assert completed.http_status == 200 and completed.status == "error"
    assert completed.trace_id == TRACE_ID
    assert correlation_id.get() == ""


def test_shutdown_flushes_all_three_signal_providers_with_a_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [Mock(), Mock(), Mock()]
    monkeypatch.setattr(monitoring.trace, "get_tracer_provider", lambda: providers[0])
    monkeypatch.setattr(monitoring, "get_logger_provider", lambda: providers[1])
    monkeypatch.setattr(monitoring.metrics, "get_meter_provider", lambda: providers[2])
    monitoring.flush_telemetry()
    for provider in providers:
        provider.force_flush.assert_called_once_with(timeout_millis=5000)


def test_monitoring_enables_manual_metrics_and_keeps_logs_independent_of_trace_sampling(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = Mock()
    monkeypatch.setattr(monitoring, "_initialized", False)
    monkeypatch.setattr(monitoring, "configure_azure_monitor", configure)
    monkeypatch.setattr(monitoring, "configure_logging", Mock())
    monkeypatch.setattr(monitoring.atexit, "register", Mock())
    settings.applicationinsights_connection_string = SecretStr(
        "InstrumentationKey=00000000-0000-0000-0000-000000000001"
    )
    settings.telemetry_enabled = True
    monitoring.configure_monitoring(settings)
    monitoring.configure_monitoring(settings)
    assert configure.call_count == 1
    assert configure.call_args.kwargs["disable_metrics"] is False
    assert configure.call_args.kwargs["enable_trace_based_sampling_for_logs"] is False
    assert configure.call_args.kwargs["enable_performance_counters"] is True
    assert configure.call_args.kwargs["enable_live_metrics"] is False
    assert all(
        not v["enabled"] for v in configure.call_args.kwargs["instrumentation_options"].values()
    )
