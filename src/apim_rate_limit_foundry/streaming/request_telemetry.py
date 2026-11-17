"""Keep a streaming request's trace alive through iteration and final accounting."""

import logging
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager
from functools import wraps
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from apim_rate_limit_foundry.request_telemetry import finish_request
from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    correlation_id,
    emit,
    request_correlation,
    request_trace_context,
)

ROUTE = "/api/stream"


def _active(span: Span) -> AbstractContextManager[Span]:
    """Make the span current without recording exception text or changing its status."""
    return trace.use_span(span, record_exception=False, set_status_on_exception=False)


def _finish(span: Span, status: int, started: float, failed: bool = False) -> None:
    """Record full stream lifetime and finish the span, including cancellation/errors."""
    finish_request(span, "POST", ROUTE, status, started, failed)
    span.end()


async def _observed(
    source: AsyncIterable[str | bytes | memoryview],
    span: Span,
    request_id: str,
    status: int,
    started: float,
) -> AsyncIterator[str | bytes | memoryview]:
    """Forward chunks and close the source before ending request telemetry."""
    token = correlation_id.set(request_id)
    failed = False
    try:
        with _active(span):
            try:
                async for chunk in source:
                    yield chunk
            except BaseException as error:
                failed = True
                emit("request_failed", level=logging.ERROR, error_type=type(error).__name__)
                raise
            finally:
                try:
                    close = getattr(source, "aclose", None)
                    if close is not None:
                        await close()
                finally:
                    _finish(span, status, started, failed)
    finally:
        correlation_id.reset(token)


def trace_stream_request(
    handler: Callable[[Request], Awaitable[Response]],
) -> Callable[[Request], Awaitable[Response]]:
    """Defer server-span completion until the returned stream has been consumed.

    Returning StreamingResponse only sends headers; iteration and usage accounting
    happen later. Re-establish task-local trace/correlation context during iteration
    so final accounting and its queued work retain the original request's trace.
    """

    @wraps(handler)
    async def wrapped(req: Request) -> Response:
        request_id = request_correlation(req.headers.get("x-correlation-id"))
        token = correlation_id.set(request_id)
        started = perf_counter()
        span = trace.get_tracer(LOGGER_NAME).start_span(
            f"POST {ROUTE}",
            context=request_trace_context(req.headers.get("traceparent")),
            kind=SpanKind.SERVER,
            attributes={
                "correlation_id": request_id,
                "http.request.method": "POST",
                "http.route": ROUTE,
            },
        )
        try:
            with _active(span):
                emit("request_started", http_method="POST", route=ROUTE)
                try:
                    response = await handler(req)
                except BaseException as error:
                    emit("request_failed", level=logging.ERROR, error_type=type(error).__name__)
                    _finish(span, 500, started, True)
                    raise
                response.headers["X-Correlation-ID"] = request_id
                if isinstance(response, StreamingResponse):
                    response.body_iterator = _observed(
                        response.body_iterator, span, request_id, response.status_code, started
                    )
                else:
                    _finish(span, response.status_code, started)
                return response
        finally:
            correlation_id.reset(token)

    return wrapped
