"""Time a domain operation as a span and scope inherited safe fields to the task."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from apim_rate_limit_foundry.telemetry.context import LOGGER_NAME, operation_context
from apim_rate_limit_foundry.telemetry.events import emit
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes
from apim_rate_limit_foundry.telemetry.timing import elapsed_ms


@contextmanager
def operation_span(operation: str, **attributes: Any) -> Iterator[None]:
    """Time a domain operation and scope inherited safe fields to the current task.

    Failures are observed then re-raised unchanged. Context is restored even on
    cancellation; no exception payload/stack is automatically attached to spans.
    """
    context = safe_attributes(
        {**(operation_context.get() or {}), **attributes, "operation": operation}
    )
    token = operation_context.set(context)
    started = perf_counter()
    try:
        with trace.get_tracer(LOGGER_NAME).start_as_current_span(
            operation,
            attributes=context,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            emit("operation_started")
            try:
                yield
            except BaseException as error:
                span.set_status(StatusCode.ERROR)
                span.set_attribute("error_type", type(error).__name__)
                emit(
                    "operation_failed",
                    level=logging.ERROR,
                    status="error",
                    error_type=type(error).__name__,
                    duration_ms=elapsed_ms(started),
                )
                raise
            else:
                span.set_status(StatusCode.OK)
                emit("operation_completed", status="ok", duration_ms=elapsed_ms(started))
    finally:
        operation_context.reset(token)
