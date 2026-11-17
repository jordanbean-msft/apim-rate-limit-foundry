"""Emit allowlisted structured events enriched with task-local trace context."""

import logging
from typing import Any

from opentelemetry import trace

from apim_rate_limit_foundry.telemetry.context import (
    LOGGER_NAME,
    correlation_id,
    operation_context,
)
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes, safe_event

USAGE_EVENT_VERSION = 2
DEFAULT_EVENT_VERSION = 1


def emit(event: str, *, level: int = logging.INFO, **attributes: Any) -> None:
    """Emit a named structured event enriched with task-local operation/trace context.

    Explicit attributes override inherited operation fields; generated trace and
    event-version fields remain authoritative. Every merged value is filtered.
    """
    name = safe_event(event)
    span = trace.get_current_span().get_span_context()
    context = safe_attributes(
        {
            **(operation_context.get() or {}),
            **attributes,
            "trace_id": f"{span.trace_id:032x}" if span.is_valid else None,
            "span_id": f"{span.span_id:016x}" if span.is_valid else None,
            "correlation_id": correlation_id.get(),
            "event_name": name,
            "event_version": USAGE_EVENT_VERSION
            if name == "usage_recorded"
            else DEFAULT_EVENT_VERSION,
        }
    )
    logging.getLogger(LOGGER_NAME).log(level, name, extra=context)
