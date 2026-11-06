"""Initialize the Microsoft distro once, with deliberately manual instrumentation.

APPLICATIONINSIGHTS_CONNECTION_STRING enables export; TELEMETRY_ENABLED=false
disables it. OTEL_SERVICE_NAME defaults to rate-limiter. Keep worker automatic
initialization flags PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY and
PYTHON_ENABLE_OPENTELEMETRY unset/false: otherwise the worker can configure root
logging/HTTP instrumentation before these safety settings take effect.

The Functions host can separately enable host.json telemetryMode=OpenTelemetry.
This process exports only the named domain logger and manually generated spans.
The SDK batches asynchronously; shutdown flushing is best-effort, not a durable
audit substitute. Accounting audit records remain in Table Storage.
"""

import atexit
from threading import Lock

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk.resources import Resource

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.telemetry import LOGGER_NAME, configure_logging, emit

_lock = Lock()
_initialized = False


def flush_telemetry() -> None:
    """Best-effort bounded drain at worker shutdown, never on the request path."""
    for provider in (trace.get_tracer_provider(), get_logger_provider()):
        flush = getattr(provider, "force_flush", None)
        if flush is not None:
            flush(timeout_millis=5000)


def configure_monitoring(settings: Settings) -> None:
    global _initialized
    configure_logging()
    connection_string = settings.applicationinsights_connection_string
    if not settings.telemetry_enabled or not connection_string:
        return
    with _lock:
        if _initialized:
            return
        configure_azure_monitor(
            connection_string=connection_string.get_secret_value(),
            logger_name=LOGGER_NAME,
            resource=Resource.create({"service.name": settings.otel_service_name}),
            sampling_ratio=1.0,
            enable_trace_based_sampling_for_logs=False,
            enable_live_metrics=False,
            enable_performance_counters=False,
            disable_metrics=True,
            disable_offline_storage=True,
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
        configure_logging()
        _initialized = True
        atexit.register(flush_telemetry)
        emit("telemetry_initialized", status="ok")
