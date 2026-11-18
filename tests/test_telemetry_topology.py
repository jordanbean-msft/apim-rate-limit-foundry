import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from azure.monitor.opentelemetry import _configure as distro
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from azure.monitor.opentelemetry.exporter._performance_counters import (
    _processor as performance_processors,
)
from azure.monitor.opentelemetry.exporter._quickpulse import _processor as live_processors
from azure.monitor.opentelemetry.exporter.export import _base as exporter_base
from azure.monitor.opentelemetry.exporter.export.trace._exporter import _convert_span_to_envelope
from azurefunctions.extensions.http.fastapi import WebApp
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import JSONResponse

from apim_rate_limit_foundry import monitoring
from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.export.event_hub_usage_publisher import EventHubUsagePublisher
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository
from apim_rate_limit_foundry.streaming.request_telemetry import trace_stream_request
from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    dependency_http_status,
    get_tracer,
    http_dependency_span,
)


@pytest.fixture
def private_monitoring(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[SimpleNamespace]:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    meter_provider = MeterProvider()
    domain_logger = logging.getLogger(LOGGER_NAME)
    original_handlers = domain_logger.handlers[:]
    monkeypatch.setattr(monitoring, "_initialized", False)
    monkeypatch.setattr(monitoring, "_logger_provider", None)
    monkeypatch.setattr(monitoring.tracing, "provider", None)
    monkeypatch.setattr(monitoring, "AzureMonitorTraceExporter", Mock(return_value=spans))
    monkeypatch.setattr(monitoring, "AzureMonitorLogExporter", Mock(return_value=logs))
    metrics_setup, tracing_setup, logging_setup = Mock(), Mock(), Mock()
    monkeypatch.setattr(distro, "get_configuration_manager", lambda: None)
    monkeypatch.setattr(distro, "_setup_metrics", metrics_setup)
    monkeypatch.setattr(distro, "_setup_tracing", tracing_setup)
    monkeypatch.setattr(distro, "_setup_logging", logging_setup)
    monkeypatch.setattr(distro, "_setup_live_metrics", Mock())
    monkeypatch.setattr(distro, "_setup_instrumentations", Mock())
    monkeypatch.setattr(distro, "_setup_browser_sdk_loader", Mock())
    monkeypatch.setattr(monitoring, "configure_azure_monitor", distro.configure_azure_monitor)
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    performance_manager = Mock()
    live_manager = Mock()
    monkeypatch.setattr(
        performance_processors, "_PerformanceCountersManager", lambda: performance_manager
    )
    monkeypatch.setattr(live_processors, "get_quickpulse_manager", lambda: live_manager)
    monkeypatch.setattr(monitoring.atexit, "register", Mock())
    monkeypatch.setattr(metrics, "get_meter_provider", lambda: meter_provider)
    settings.applicationinsights_connection_string = SecretStr(
        "InstrumentationKey=00000000-0000-0000-0000-000000000001"
    )
    settings.otel_performance_counters_enabled = True
    settings.otel_live_metrics_enabled = True
    settings.telemetry_enabled = True
    settings.otel_traces_sampler_arg = getattr(request, "param", 1.0)
    settings.website_site_name = "sample-function"
    monkeypatch.setenv("OTEL_SERVICE_NAME", "legacy-worker-alias")
    before = trace.get_tracer_provider(), get_logger_provider()
    monitoring.configure_monitoring(settings)
    try:
        yield SimpleNamespace(
            spans=spans,
            logs=logs,
            global_providers=before,
            performance=performance_manager,
            live=live_manager,
            metrics_setup=metrics_setup,
            tracing_setup=tracing_setup,
            logging_setup=logging_setup,
        )
    finally:
        monitoring.tracing.provider.shutdown()
        monitoring._logger_provider.shutdown()
        meter_provider.shutdown()
        for handler in domain_logger.handlers[:]:
            if handler not in original_handlers:
                domain_logger.removeHandler(handler)
                handler.close()


def test_distro_configures_metrics_without_global_trace_or_log_exporters(
    private_monitoring: SimpleNamespace,
) -> None:
    private_monitoring.metrics_setup.assert_called_once()
    private_monitoring.tracing_setup.assert_not_called()
    private_monitoring.logging_setup.assert_not_called()
    assert (
        trace.get_tracer_provider(),
        get_logger_provider(),
    ) == private_monitoring.global_providers


async def test_real_fastapi_apps_export_only_manual_request_spans_and_safe_logs(
    settings: Settings,
    gateway: GatewayServices,
    private_monitoring: SimpleNamespace,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, gateway)), base_url="http://test"
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/private-path?secret=private-query")).status_code == 404

    @trace_stream_request
    async def stream(req: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    extension = WebApp()
    extension.route(stream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=extension.get_app()), base_url="http://test"
    ) as client:
        assert (await client.post("/api/stream")).status_code == 200

    monitoring.flush_telemetry()
    spans = private_monitoring.spans.get_finished_spans()
    assert len(spans) == 3
    assert all(span.kind == SpanKind.SERVER for span in spans)
    assert {span.name for span in spans} == {"GET /api/health", "GET unmatched", "POST /api/stream"}
    assert all(span.instrumentation_scope.name == LOGGER_NAME for span in spans)
    assert {_convert_span_to_envelope(span).tags["ai.cloud.role"] for span in spans} == {
        "sample-function"
    }
    assert (
        trace.get_tracer_provider(),
        get_logger_provider(),
    ) == private_monitoring.global_providers
    exported_logs = private_monitoring.logs.get_finished_logs()
    assert sum(record.log_record.body == "request_completed" for record in exported_logs) == 3
    assert all(record.instrumentation_scope.name == LOGGER_NAME for record in exported_logs)
    for manager in (private_monitoring.performance, private_monitoring.live):
        assert [call.args[0] for call in manager._record_span.call_args_list] == list(spans)
        assert manager._record_log_record.call_count == len(exported_logs)
    serialized = repr(spans) + repr([record.to_json() for record in exported_logs])
    assert "private-path" not in serialized and "private-query" not in serialized


@pytest.mark.parametrize("private_monitoring", [0.0], indirect=True)
async def test_private_logs_are_exported_even_when_request_spans_are_unsampled(
    settings: Settings, gateway: GatewayServices, private_monitoring: SimpleNamespace
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, gateway)), base_url="http://test"
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
    monitoring.flush_telemetry()
    assert not private_monitoring.spans.get_finished_spans()
    completed = [
        record.log_record
        for record in private_monitoring.logs.get_finished_logs()
        if record.log_record.body == "request_completed"
    ]
    assert len(completed) == 1
    assert completed[0].trace_id != 0


def test_actual_azure_export_uses_the_private_provider_resource(
    private_monitoring: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(exporter_base, "get_configuration_manager", lambda: None)
    monkeypatch.setattr(exporter_base.BaseExporter, "_should_collect_stats", lambda self: False)
    monkeypatch.setattr(
        exporter_base.BaseExporter, "_should_collect_customer_sdkstats", lambda self: False
    )
    transmit = Mock(return_value=exporter_base.ExportResult.SUCCESS)
    monkeypatch.setattr(exporter_base.BaseExporter, "_transmit", transmit)
    exporter = AzureMonitorTraceExporter(**monitoring.AzureMonitorTraceExporter.call_args.kwargs)
    try:
        with get_tracer().start_as_current_span("request", kind=SpanKind.SERVER):
            pass
        monitoring.flush_telemetry()
        assert (
            exporter.export(private_monitoring.spans.get_finished_spans())
            == SpanExportResult.SUCCESS
        )
        envelopes = transmit.call_args.args[0]
        assert {envelope.data.base_type for envelope in envelopes} == {"MetricData", "RequestData"}
        assert {envelope.tags["ai.cloud.role"] for envelope in envelopes} == {"sample-function"}
        assert "Failed to derive Resource" not in caplog.text
    finally:
        exporter.shutdown()


async def test_exported_dependencies_identify_configured_resources_and_event_hub(
    settings: Settings, private_monitoring: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.redis_host = "cache.example.net"
    settings.event_hub_fqdn = "events.servicebus.windows.net"
    settings.event_hub_name = "usage"
    redis = RedisCounters(settings, None, Mock(get=AsyncMock(return_value=None)))
    table = TableRepository(
        Mock(get_entity=AsyncMock(return_value={"payload": json.dumps({"id": "safe"})})),
        dependency_address="storage.table.core.windows.net",
    )
    producer = Mock(
        create_batch=AsyncMock(return_value=Mock()), send_batch=AsyncMock(), close=AsyncMock()
    )
    monkeypatch.setattr(
        "apim_rate_limit_foundry.export.event_hub_usage_publisher.EventHubProducerClient",
        Mock(return_value=producer),
    )
    with get_tracer().start_as_current_span("request", kind=SpanKind.SERVER):
        with http_dependency_span(
            "provider.stream_open", "model-provider", server_address="models.openai.azure.com"
        ) as span:
            dependency_http_status(span, 200)
        await redis.configuration()
        await table.get("organizations", "safe")
        await EventHubUsagePublisher(settings, AsyncMock()).publish(
            {"event_id": "event-1", "request_id": "request-1", "tenant_ref": "t", "user_ref": "u"}
        )
    monitoring.flush_telemetry()
    spans = private_monitoring.spans.get_finished_spans()
    parent = next(span for span in spans if span.name == "request")
    dependencies = [span for span in spans if span.kind != SpanKind.SERVER]
    assert len(dependencies) == 4
    assert all(span.parent.span_id == parent.context.span_id for span in dependencies)
    exported = [_convert_span_to_envelope(span).data.base_data for span in dependencies]
    assert {(item.type, item.target) for item in exported} == {
        ("HTTP", "models.openai.azure.com"),
        ("redis", "cache.example.net"),
        ("azure.table", "storage.table.core.windows.net"),
        ("Queue Message | Microsoft.EventHub", "events.servicebus.windows.net/usage"),
    }
    assert all(not span.events for span in dependencies)
    assert not any(
        key in span.attributes
        for span in dependencies
        for key in ("url.full", "http.url", "db.statement", "messaging.message.body")
    )
