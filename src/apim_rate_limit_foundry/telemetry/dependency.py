"""Observe outbound dependencies without URLs, payloads, credentials or error text."""

import logging
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from functools import wraps
from time import perf_counter
from typing import Any

from opentelemetry import trace
from opentelemetry.metrics import get_meter
from opentelemetry.trace import Span, SpanKind, StatusCode

from apim_rate_limit_foundry.telemetry.context import LOGGER_NAME, correlation_id
from apim_rate_limit_foundry.telemetry.events import emit
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes
from apim_rate_limit_foundry.telemetry.timing import elapsed_ms

# Kept here, not in rate_limit_metrics, because that module itself depends on emit().
_DEPENDENCY_DURATION = get_meter(LOGGER_NAME).create_histogram(
    "limiter.dependency.duration", unit="ms"
)
_ERROR_STATUS_FLOOR = 300


def _mark_error(span: Span, error_type: str) -> None:
    """Flag a span failed with a class-level error type, deliberately omitting error text."""
    span.set_status(StatusCode.ERROR)
    span.set_attribute("error_type", error_type)
    span.set_attribute("error.type", error_type)


def dependency_error(span: Span, error: BaseException) -> None:
    """Attach exception class and optional status to a span."""
    _mark_error(span, type(error).__name__)
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and 100 <= status <= 599:
        span.set_attribute("http.response.status_code", status)


def dependency_http_status(span: Span, status: int) -> None:
    """Classify a completed dependency HTTP status without reading its response body."""
    span.set_attribute("http.response.status_code", status)
    if status >= _ERROR_STATUS_FLOOR:
        _mark_error(span, f"http_{status}")
    else:
        span.set_status(StatusCode.OK)


@contextmanager
def http_dependency_span(name: str, service: str, method: str = "POST") -> Iterator[Span]:
    """Observe outbound HTTP without URLs, headers, payloads or exception messages."""
    with trace.get_tracer(LOGGER_NAME).start_as_current_span(
        name,
        kind=SpanKind.CLIENT,
        attributes={"http.request.method": method, "peer.service": service},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as error:
            dependency_error(span, error)
            raise


def _semantic_attributes(dependency: str, operation: str) -> dict[str, str]:
    """Database/RPC semantic-convention attributes for the known dependency kinds."""
    if dependency in ("redis", "table"):
        return {
            "db.system": "redis" if dependency == "redis" else "azure.table",
            "db.operation": operation,
        }
    if dependency == "managed-identity":
        return {"rpc.system": "azure.identity", "rpc.method": operation}
    return {}


@contextmanager
def dependency_span(dependency: str, operation: str) -> Iterator[Span]:
    """Time one datastore/identity call with safe database/RPC semantic attributes.

    Only dependency and operation names are exported: query text, entity contents,
    connection strings, scopes and tokens must never be supplied as attributes.
    """
    start = perf_counter()
    attributes = safe_attributes(
        {"dependency": dependency, "operation": operation, "correlation_id": correlation_id.get()}
    )
    with trace.get_tracer(LOGGER_NAME).start_as_current_span(
        f"{dependency}.{operation}",
        kind=SpanKind.CLIENT,
        attributes={
            **attributes,
            **_semantic_attributes(dependency, operation),
            "peer.service": dependency,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as error:
            # Observe and re-raise unchanged; exception messages/stacks may contain credentials.
            _mark_error(span, type(error).__name__)
            _completed(dependency, operation, attributes, start, "error", type(error).__name__)
            raise
        else:
            span.set_status(StatusCode.OK)
            _completed(dependency, operation, attributes, start, "ok")


def _completed(
    dependency: str,
    operation: str,
    attributes: dict[str, Any],
    start: float,
    status: str,
    error_type: str | None = None,
) -> None:
    """Log one dependency outcome and record its latency metric (dependency/operation only)."""
    duration_ms = elapsed_ms(start)
    emit(
        "dependency_completed",
        level=logging.ERROR if error_type else logging.INFO,
        **attributes,
        status=status,
        error_type=error_type,
        duration_ms=duration_ms,
    )
    _DEPENDENCY_DURATION.record(
        duration_ms, {"dependency": dependency, "operation": operation, "status": status}
    )


def observe_dependency[**P, T](
    dependency: str,
    operation: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Wrap an async dependency while preserving its arguments, result and failures."""

    def decorate(function: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with dependency_span(dependency, operation):
                return await function(*args, **kwargs)

        return wrapped

    return decorate
