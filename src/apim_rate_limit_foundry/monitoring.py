"""Initialize Microsoft exporters once, with application-owned traces and logs.

APPLICATIONINSIGHTS_CONNECTION_STRING enables export; TELEMETRY_ENABLED=false
disables it. OTEL_SERVICE_NAME defaults to rate-limiter. Keep worker automatic
initialization flags PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY and
PYTHON_ENABLE_OPENTELEMETRY unset/false: otherwise the worker can configure root
logging/HTTP instrumentation before these safety settings take effect.

Private trace/log providers prevent FastAPI's native telemetry from collecting
duplicate requests, raw paths and exception details, including in the streaming
extension's internally constructed FastAPI app. The distro owns only metrics.
The SDK batches asynchronously; shutdown flushing is best-effort, not a durable
audit substitute. Accounting audit records remain in Table Storage.
"""

import atexit
import logging
from os import environ
from threading import Lock

from azure.monitor.opentelemetry import configure_azure_monitor
from azure.monitor.opentelemetry.exporter import (
    ApplicationInsightsSampler,
    AzureMonitorLogExporter,
    AzureMonitorTraceExporter,
)
from azure.monitor.opentelemetry.exporter._performance_counters._processor import (
    _PerformanceCountersLogRecordProcessor,
    _PerformanceCountersSpanProcessor,
)
from azure.monitor.opentelemetry.exporter._quickpulse._processor import (
    _QuickpulseLogRecordProcessor,
    _QuickpulseSpanProcessor,
)
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics.view import DropAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.telemetry import LOGGER_NAME, configure_logging, emit, tracing

_lock = Lock()
_initialized = False
_logger_provider: LoggerProvider | None = None


def flush_telemetry() -> None:
    """Best-effort bounded drain at worker shutdown, never on the request path."""
    for provider in (
        tracing.provider or trace.get_tracer_provider(),
        _logger_provider or get_logger_provider(),
        metrics.get_meter_provider(),
    ):
        flush = getattr(provider, "force_flush", None)
        if flush is not None:
            flush(timeout_millis=5000)


def configure_monitoring(settings: Settings) -> None:
    """Install named, privacy-filtered Microsoft telemetry once per worker process.

    Always enable safe local logging. Cloud export additionally requires an enabled
    flag and connection string; initialization is locked across concurrent callers.
    Export batching never supplies accounting durability or request-path flushing.
    """
    global _initialized, _logger_provider
    configure_logging()
    connection_string = settings.applicationinsights_connection_string
    if not settings.telemetry_enabled or not connection_string:
        return
    with _lock:
        if _initialized:
            return
        resource = Resource.create(
            {"service.name": settings.website_site_name or settings.otel_service_name}
        )
        exporter_options = {
            "connection_string": connection_string.get_secret_value(),
            "disable_offline_storage": True,
        }
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=ApplicationInsightsSampler(settings.otel_traces_sampler_arg),
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                AzureMonitorTraceExporter(**exporter_options, tracer_provider=tracer_provider)
            )
        )
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(AzureMonitorLogExporter(**exporter_options))
        )
        tracing.provider = tracer_provider
        _logger_provider = logger_provider
        logging.getLogger(LOGGER_NAME).addHandler(LoggingHandler(logger_provider=logger_provider))
        # The distro overwrites signal keyword switches with these standard environment controls.
        environ["OTEL_TRACES_EXPORTER"] = "none"
        environ["OTEL_LOGS_EXPORTER"] = "none"
        configure_azure_monitor(
            **exporter_options,
            logger_name=LOGGER_NAME,
            resource=resource,
            sampling_ratio=settings.otel_traces_sampler_arg,
            enable_trace_based_sampling_for_logs=False,
            enable_live_metrics=settings.otel_live_metrics_enabled,
            enable_performance_counters=settings.otel_performance_counters_enabled,
            views=[View(meter_name="fastapi", aggregation=DropAggregation())],
            # Automatic HTTP/SDK spans can capture URLs, query strings and exception text.
            instrumentation_options={
                name: {"enabled": False}
                for name in (
                    "azure_sdk",
                    "django",
                    "fastapi",
                    "flask",
                    "psycopg2",
                    "requests",
                    "urllib",
                    "urllib3",
                    "httpx",
                    "httpx2",
                )
            },
        )
        # The distro normally attaches these processors to its global providers.
        if settings.otel_performance_counters_enabled:
            tracer_provider.add_span_processor(_PerformanceCountersSpanProcessor())
            logger_provider.add_log_record_processor(_PerformanceCountersLogRecordProcessor())
        if settings.otel_live_metrics_enabled:
            tracer_provider.add_span_processor(_QuickpulseSpanProcessor())
            logger_provider.add_log_record_processor(_QuickpulseLogRecordProcessor())
        # Apply the domain privacy filter to the private exporter handler as well.
        configure_logging()
        _initialized = True
        atexit.register(flush_telemetry)
        emit("telemetry_initialized", status="ok")
