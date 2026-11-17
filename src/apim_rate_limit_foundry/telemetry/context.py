"""Task-local correlation and W3C trace context, validated before use or propagation."""

import re
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from apim_rate_limit_foundry.telemetry.sanitizer import safe_id

LOGGER_NAME = "apim_rate_limit_foundry"
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
# Safe fields inherited by every event emitted inside an ``operation_span``.
operation_context: ContextVar[dict[str, Any] | None] = ContextVar("operation_context", default=None)
_TRACEPARENT = re.compile(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}\Z")


def request_correlation(value: str | None) -> str:
    """Reuse a valid incoming correlation ID or generate an untrusted-input-free one."""
    return safe_id(value) or uuid4().hex


def request_trace_context(value: str | None) -> Context | None:
    """Extract a valid version-00 W3C parent or decline to join the supplied trace."""
    if not value or not _TRACEPARENT.fullmatch(value):
        return None
    context = TraceContextTextMapPropagator().extract({"traceparent": value})
    return context if trace.get_current_span(context).get_span_context().is_valid else None


def outgoing_trace_headers(request_id: str | None = None) -> dict[str, str]:
    """Propagate only traceparent and a sanitized request/correlation identifier."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    headers = {"traceparent": carrier["traceparent"]} if "traceparent" in carrier else {}
    value = safe_id(request_id) or safe_id(correlation_id.get())
    if value:
        headers["X-Correlation-ID"] = value
    return headers
