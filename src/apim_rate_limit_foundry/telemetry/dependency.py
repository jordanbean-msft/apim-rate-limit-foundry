"""Observe outbound dependencies without URLs, payloads, credentials or error text."""

import logging
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from functools import wraps
from time import perf_counter
from typing import Any, Concatenate, Protocol

from opentelemetry.metrics import get_meter
from opentelemetry.trace import Span, SpanKind, StatusCode

from apim_rate_limit_foundry.telemetry.context import LOGGER_NAME, correlation_id
from apim_rate_limit_foundry.telemetry.events import emit
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes
from apim_rate_limit_foundry.telemetry.timing import elapsed_ms
from apim_rate_limit_foundry.telemetry.tracing import get_tracer

# Kept here, not in rate_limit_metrics, because that module itself depends on emit().
_DEPENDENCY_DURATION = get_meter(LOGGER_NAME).create_histogram(
    "limiter.dependency.duration", unit="ms"
)
_ERROR_STATUS_FLOOR = 300


class DependencyTarget(Protocol):
    """Expose the configured resource hostname, never a connection string or request URL."""

    @property
    def dependency_address(self) -> str: ...


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
def http_dependency_span(
    name: str, service: str, method: str = "POST", *, server_address: str = ""
) -> Iterator[Span]:
    """Observe outbound HTTP without URLs, headers, payloads or exception messages."""
    attributes = {"http.request.method": method, "peer.service": server_address or service}
    if server_address:
        attributes["server.address"] = server_address
    with get_tracer().start_as_current_span(
        name,
        kind=SpanKind.CLIENT,
        attributes=attributes,
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
    if dependency == "event-hub":
        return {
            "az.namespace": "Microsoft.EventHub",
            "messaging.system": "eventhubs",
            "messaging.operation.name": operation,
            "messaging.operation.type": "send",
        }
    return {}


@contextmanager
def dependency_span(
    dependency: str,
    operation: str,
    *,
    server_address: str = "",
    server_port: int | None = None,
    destination: str = "",
) -> Iterator[Span]:
    """Time one datastore/identity call with safe database/RPC semantic attributes.

    Resource hostnames and messaging destinations identify map nodes. Query text,
    entity contents, connection strings, scopes and tokens must never be supplied.
    """
    start = perf_counter()
    attributes = safe_attributes(
        {"dependency": dependency, "operation": operation, "correlation_id": correlation_id.get()}
    )
    semantics: dict[str, str | int] = {
        **_semantic_attributes(dependency, operation),
        "peer.service": server_address or dependency,
    }
    if server_address:
        semantics["server.address"] = server_address
    if server_port is not None:
        semantics["server.port"] = server_port
    if destination:
        semantics["messaging.destination.name"] = destination
    with get_tracer().start_as_current_span(
        f"{dependency}.{operation}",
        kind=SpanKind.PRODUCER if dependency == "event-hub" else SpanKind.CLIENT,
        attributes={
            **attributes,
            **semantics,
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


def observe_dependency[S: DependencyTarget, **P, T](
    dependency: str,
    operation: str,
) -> Callable[
    [Callable[Concatenate[S, P], Awaitable[T]]], Callable[Concatenate[S, P], Coroutine[Any, Any, T]]
]:
    """Wrap an async dependency while preserving its arguments, result and failures."""

    def decorate(
        function: Callable[Concatenate[S, P], Awaitable[T]],
    ) -> Callable[Concatenate[S, P], Coroutine[Any, Any, T]]:
        @wraps(function)
        async def wrapped(self: S, /, *args: P.args, **kwargs: P.kwargs) -> T:
            with dependency_span(dependency, operation, server_address=self.dependency_address):
                return await function(self, *args, **kwargs)

        return wrapped

    return decorate
