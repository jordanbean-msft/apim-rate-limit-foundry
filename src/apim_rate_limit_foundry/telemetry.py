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
from opentelemetry.trace import SpanKind, StatusCode

LOGGER_NAME = "apim_rate_limit_foundry"
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_FIELDS = frozenset(
    {
        "correlation_id",
        "reservation_id",
        "allowed",
        "service",
        "model",
        "api_protocol",
        "error_type",
        "operation",
        "status",
        "reason",
        "remaining",
        "estimated",
        "retry_after",
        "matched_policy_ids",
        "denied_policy_ids",
        "policy_id",
        "metric",
        "amount",
        "limit",
        "reset_at",
        "price_id",
        "price_version",
        "cost_micro_usd",
        "cached_input_reported",
        "cache_write_input_reported",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens_5m",
        "cache_write_input_tokens_1h",
        "pages",
        "text_records",
        "requests",
        "input_per_million",
        "output_per_million",
        "cached_input_per_million",
        "cache_write_5m_per_million",
        "cache_write_1h_per_million",
        "per_page",
        "per_text_record",
        "per_request",
        "collection",
        "action",
        "records",
        "duration_ms",
        "dependency",
        "http_method",
        "http_status",
        "route",
        "past_due",
        "replayed",
        "stage",
    }
)
_TEXT_FIELDS = frozenset({"route", "reset_at"})
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
        "request_completed",
        "request_rejected",
        "limiter_dependency_unavailable",
        "configuration_written",
        "durable_record_read",
        "durable_record_replayed",
        "rate_decision",
        "reservation_policy_debit",
        "settlement_recorded",
        "settlement_price",
        "settlement_policy_debit",
        "settlement_pending",
        "reconciliation_completed",
        "recovery_completed",
        "recovery_started",
        "operation_ownership",
        "idempotency_conflict",
        "reservation_requested",
        "reservation_intent_replayed",
        "counter_reservation_evaluated",
        "settlement_requested",
        "reconciliation_timer_started",
        "reconciliation_timer_completed",
        "reconciliation_timer_failed",
    }
)


def safe_event(value: object) -> str:
    return value if isinstance(value, str) and value in _EVENTS else "application_event"


def safe_id(value: str | None) -> str | None:
    return value if value and _SAFE_ID.fullmatch(value) else None


def request_correlation(value: str | None) -> str:
    return safe_id(value) or uuid4().hex


def safe_attributes(values: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in _FIELDS or value is None:
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
        elif key in ("matched_policy_ids", "denied_policy_ids") and isinstance(value, list):
            result[key] = [item for item in value[:128] if isinstance(item, str) and safe_id(item)]
    return result


def emit(event: str, *, level: int = logging.INFO, **attributes: Any) -> None:
    context = safe_attributes({**attributes, "correlation_id": correlation_id.get()})
    logging.getLogger(LOGGER_NAME).log(level, safe_event(event), extra=context)


class JsonFormatter(logging.Formatter):
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
    def decorate(function: Callable[_P, Awaitable[_T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
        @wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with dependency_span(dependency, operation):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


def observe_operation(
    operation: str,
) -> Callable[[Callable[_P, Awaitable[_T]]], Callable[_P, Coroutine[Any, Any, _T]]]:
    def decorate(function: Callable[_P, Awaitable[_T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
        @wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            start = perf_counter()
            emit("operation_started", operation=operation)
            try:
                result = await function(*args, **kwargs)
            except Exception as error:
                emit(
                    "operation_failed",
                    level=logging.ERROR,
                    operation=operation,
                    error_type=type(error).__name__,
                    status="error",
                    **({"allowed": False} if operation == "reserve" else {}),
                    duration_ms=round((perf_counter() - start) * 1000, 3),
                )
                raise
            emit(
                "operation_completed",
                operation=operation,
                status="ok",
                duration_ms=round((perf_counter() - start) * 1000, 3),
            )
            return result

        return wrapped

    return decorate


@contextmanager
def dependency_span(dependency: str, operation: str) -> Iterator[None]:
    start = perf_counter()
    attributes = safe_attributes(
        {"dependency": dependency, "operation": operation, "correlation_id": correlation_id.get()}
    )
    with trace.get_tracer(LOGGER_NAME).start_as_current_span(
        f"{dependency}.{operation}",
        kind=SpanKind.CLIENT,
        attributes={
            **attributes,
            "db.system": "redis" if dependency == "redis" else "azure.table",
            "db.operation": operation,
            "peer.service": dependency,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except Exception as error:
            # Observe and re-raise unchanged; exception messages/stacks may contain credentials.
            span.set_status(StatusCode.ERROR)
            span.set_attribute("error_type", type(error).__name__)
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
