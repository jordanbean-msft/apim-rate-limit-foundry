"""Allowlisted structured telemetry: events, spans, dependency timing and log setup.

Import from this package rather than its submodules. Nothing here serializes
prompts, generated content, credentials, raw identities or exception text.
"""

from apim_rate_limit_foundry.telemetry.context import (
    LOGGER_NAME,
    correlation_id,
    outgoing_trace_headers,
    request_correlation,
    request_trace_context,
)
from apim_rate_limit_foundry.telemetry.dependency import (
    dependency_error,
    dependency_http_status,
    dependency_span,
    http_dependency_span,
    observe_dependency,
)
from apim_rate_limit_foundry.telemetry.events import emit
from apim_rate_limit_foundry.telemetry.log_config import (
    JsonFormatter,
    SafeTelemetryFilter,
    configure_logging,
)
from apim_rate_limit_foundry.telemetry.operation import operation_span
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes, safe_event, safe_id
from apim_rate_limit_foundry.telemetry.service_requests import (
    record_service_response,
    record_table_response,
)
from apim_rate_limit_foundry.telemetry.timing import elapsed_ms
from apim_rate_limit_foundry.telemetry.tracing import get_tracer

__all__ = [
    "LOGGER_NAME",
    "JsonFormatter",
    "SafeTelemetryFilter",
    "configure_logging",
    "correlation_id",
    "dependency_error",
    "dependency_http_status",
    "dependency_span",
    "elapsed_ms",
    "emit",
    "get_tracer",
    "http_dependency_span",
    "observe_dependency",
    "operation_span",
    "outgoing_trace_headers",
    "record_service_response",
    "record_table_response",
    "request_correlation",
    "request_trace_context",
    "safe_attributes",
    "safe_event",
    "safe_id",
]
