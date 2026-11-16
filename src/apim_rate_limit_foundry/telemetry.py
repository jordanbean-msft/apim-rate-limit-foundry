"""Allowlisted domain telemetry: never serialize payloads, identities or exceptions."""

import json
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

LOGGER_NAME = "apim_rate_limit_foundry"
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_operation_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "operation_context", default=None
)
_TRACEPARENT = re.compile(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_SUBSCRIPTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}\Z")
_FIELDS = frozenset(
    {
        "correlation_id",
        "event_name",
        "event_version",
        "event_id",
        "request_id",
        "trace_id",
        "span_id",
        "tenant_ref",
        "user_ref",
        "team_id",
        "department_id",
        "budget_id",
        "budget_ids",
        "budget_model",
        "budget_count",
        "denied_budget_count",
        "denied_budget_ids",
        "subject_type",
        "subject_id",
        "month",
        "limit_micro_usd",
        "spent_micro_usd",
        "remaining_micro_usd",
        "business_unit",
        "cost_center",
        "allowed",
        "model",
        "api_protocol",
        "error_type",
        "operation",
        "status",
        "reason",
        "retry_after",
        "reset_at",
        "price_version",
        "cost_micro_usd",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "cost_basis",
        "out_of_bounds",
        "uncached_input_tokens",
        "total_tokens",
        "cache_hit",
        "collection",
        "record_id",
        "pending",
        "action",
        "records",
        "duration_ms",
        "dependency",
        "http_method",
        "http_status",
        "route",
        "replayed",
        "subscription_id",
        "streaming",
    }
)
_TEXT_FIELDS = frozenset({"route", "reset_at", "month", "business_unit", "cost_center"})
_P = ParamSpec("_P")
_T = TypeVar("_T")
_LOG_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_EVENTS = frozenset(
    {
        "application_event",
        "decision",
        "telemetry_initialized",
        "dependency_completed",
        "operation_started",
        "operation_completed",
        "operation_failed",
        "request_failed",
        "request_started",
        "request_completed",
        "request_rejected",
        "limiter_dependency_unavailable",
        "configuration_written",
        "durable_record_read",
        "durable_record_replayed",
        "budget_decision",
        "budget_evaluated",
        "budget_status",
        "usage_recorded",
        "usage_record_replayed",
        "usage_event_publish_failed",
        "usage_event_publish_accepted",
        "stream_usage_unknown",
        "usage_record_failed",
        "configuration_cache_loaded",
        "background_write_dropped",
        "background_write_failed",
        "background_write_completed",
        "background_worker_failed",
        "background_writes_abandoned",
        "idempotency_conflict",
        "dashboard_unavailable",
        "dashboard_timeout",
        "configuration_record_invalid",
        "usage_out_of_bounds",
        "dashboard_query_failed",
        "metric_record_failed",
    }
)


def safe_event(value: object) -> str:
    """Collapse unknown log messages to a fixed event name, never raw free text."""
    return value if isinstance(value, str) and value in _EVENTS else "application_event"


def safe_id(value: str | None) -> str | None:
    """Accept only bounded correlation/attribute identifiers safe for export."""
    return value if value and _SAFE_ID.fullmatch(value) else None


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


def dependency_error(span: Span, error: BaseException) -> None:
    """Attach exception class and optional status, deliberately omitting error text."""
    span.set_status(StatusCode.ERROR)
    span.set_attribute("error_type", type(error).__name__)
    span.set_attribute("error.type", type(error).__name__)
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and 100 <= status <= 599:
        span.set_attribute("http.response.status_code", status)


def dependency_http_status(span: Span, status: int) -> None:
    """Classify a completed dependency HTTP status without reading its response body."""
    span.set_attribute("http.response.status_code", status)
    span.set_status(StatusCode.ERROR if status >= 300 else StatusCode.OK)
    if status >= 300:
        span.set_attribute("error_type", f"http_{status}")
        span.set_attribute("error.type", f"http_{status}")


def safe_attributes(values: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only bounded allowlisted scalar/list attributes into logs and spans.

    This is a second boundary after caller-side minimization: unknown fields,
    nonfinite floats, invalid identifiers and oversized values are discarded.
    It is not a general-purpose serializer for request or provider objects.
    """
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in _FIELDS or value is None:
            continue
        if key in ("model", "budget_model") and value == "*":
            result[key] = value
            continue
        if key == "subscription_id" and not (
            isinstance(value, str) and _SAFE_SUBSCRIPTION_ID.fullmatch(value)
        ):
            continue
        if key == "streaming" and not isinstance(value, bool):
            continue
        if isinstance(value, bool | int):
            result[key] = value
        elif isinstance(value, float):
            if value == value and abs(value) != float("inf"):
                result[key] = value
        elif isinstance(value, str):
            if key in _TEXT_FIELDS:
                if len(value) <= 160 and not any(c in value for c in ("\r", "\n", "?", "#")):
                    result[key] = value
            elif safe_id(value):
                result[key] = value
        elif key in (
            "budget_ids",
            "denied_budget_ids",
        ) and isinstance(value, list):
            result[key] = [item for item in value[:128] if isinstance(item, str) and safe_id(item)]
    return result


def emit(event: str, *, level: int = logging.INFO, **attributes: Any) -> None:
    """Emit a named structured event enriched with task-local operation/trace context.

    Explicit attributes override inherited operation fields; generated trace and
    event-version fields remain authoritative. Every merged value is filtered.
    """
    name = safe_event(event)
    span = trace.get_current_span().get_span_context()
    context = safe_attributes(
        {
            **(_operation_context.get() or {}),
            **attributes,
            "trace_id": f"{span.trace_id:032x}" if span.is_valid else None,
            "span_id": f"{span.span_id:016x}" if span.is_valid else None,
            "correlation_id": correlation_id.get(),
            "event_name": name,
            "event_version": 2 if name == "usage_recorded" else 1,
        }
    )
    logging.getLogger(LOGGER_NAME).log(level, name, extra=context)


@contextmanager
def operation_span(operation: str, **attributes: Any) -> Iterator[None]:
    """Time a domain operation and scope inherited safe fields to the current task.

    Failures are observed then re-raised unchanged. Context is restored even on
    cancellation; no exception payload/stack is automatically attached to spans.
    """
    context = safe_attributes(
        {**(_operation_context.get() or {}), **attributes, "operation": operation}
    )
    token = _operation_context.set(context)
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
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                )
                raise
            else:
                span.set_status(StatusCode.OK)
                emit(
                    "operation_completed",
                    status="ok",
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                )
    finally:
        _operation_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Write the same restricted event schema to stdout as to cloud telemetry."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "event": safe_event(record.msg),
                **safe_attributes(record.__dict__),
            }
        )


class SafeTelemetryFilter(logging.Filter):
    """Sanitize before either stdout formatting or the OTel handler sees the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Remove unsafe extras and exception material in-place before any exporter."""
        attributes = safe_attributes(record.__dict__)
        for name in tuple(record.__dict__):
            if name not in _LOG_FIELDS:
                del record.__dict__[name]
        record.__dict__.update(attributes)
        record.msg = safe_event(record.msg)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging() -> None:
    """Idempotently configure domain handlers and suppress noisy credential loggers."""
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonFormatter())
        logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if not any(isinstance(f, SafeTelemetryFilter) for f in handler.filters):
            handler.addFilter(SafeTelemetryFilter())
    # The explicit distro handler below exports this logger, not the Functions root logger.
    logger.propagate = False
    for name in ("azure.core.pipeline.policies.http_logging_policy", "azure.identity"):
        logging.getLogger(name).setLevel(logging.WARNING)


def observe_dependency(
    dependency: str,
    operation: str,
) -> Callable[[Callable[_P, Awaitable[_T]]], Callable[_P, Coroutine[Any, Any, _T]]]:
    """Wrap an async dependency while preserving its arguments, result and failures."""

    def decorate(function: Callable[_P, Awaitable[_T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
        @wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with dependency_span(dependency, operation):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


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
    if dependency in ("redis", "table"):
        attributes.update(
            {
                "db.system": "redis" if dependency == "redis" else "azure.table",
                "db.operation": operation,
            }
        )
    elif dependency == "managed-identity":
        attributes.update({"rpc.system": "azure.identity", "rpc.method": operation})
    with trace.get_tracer(LOGGER_NAME).start_as_current_span(
        f"{dependency}.{operation}",
        kind=SpanKind.CLIENT,
        attributes={
            **attributes,
            "peer.service": dependency,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as error:
            # Observe and re-raise unchanged; exception messages/stacks may contain credentials.
            span.set_status(StatusCode.ERROR)
            span.set_attribute("error_type", type(error).__name__)
            span.set_attribute("error.type", type(error).__name__)
            emit(
                "dependency_completed",
                level=logging.ERROR,
                **attributes,
                status="error",
                error_type=type(error).__name__,
                duration_ms=round((perf_counter() - start) * 1000, 3),
            )
            raise
        else:
            span.set_status(StatusCode.OK)
            emit(
                "dependency_completed",
                **attributes,
                status="ok",
                duration_ms=round((perf_counter() - start) * 1000, 3),
            )
