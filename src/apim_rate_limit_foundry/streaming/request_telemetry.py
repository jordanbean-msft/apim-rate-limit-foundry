"""Keep a streaming request's trace alive through iteration and final accounting."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import wraps
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, StatusCode
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    correlation_id,
    emit,
    request_correlation,
    request_trace_context,
)


def _finish(span: Span, status: int, started: float, failed: bool = False) -> None:
    """Record full stream lifetime and finish the span, including cancellation/errors."""
    failed = failed or status >= 500
    outcome = "error" if failed else "rejected" if status >= 400 else "ok"
    duration = round((perf_counter() - started) * 1000, 3)
    span.set_attribute("http.response.status_code", status)
    span.set_status(StatusCode.ERROR if failed else StatusCode.OK)
    rate_metrics.request("POST", "/api/stream", status, duration, outcome)
    emit(
        "request_completed",
        level=logging.ERROR if failed else logging.INFO,
        http_method="POST",
        route="/api/stream",
        http_status=status,
        duration_ms=duration,
        status=outcome,
    )
    span.end()


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
            "POST /api/stream",
            context=request_trace_context(req.headers.get("traceparent")),
            kind=SpanKind.SERVER,
            attributes={
                "correlation_id": request_id,
                "http.request.method": "POST",
                "http.route": "/api/stream",
            },
        )
        try:
            with trace.use_span(span, record_exception=False, set_status_on_exception=False):
                emit("request_started", http_method="POST", route="/api/stream")
                try:
                    response = await handler(req)
                except BaseException as error:
                    emit("request_failed", level=logging.ERROR, error_type=type(error).__name__)
                    _finish(span, 500, started, True)
                    raise
                response.headers["X-Correlation-ID"] = request_id
                if isinstance(response, StreamingResponse):
                    source = response.body_iterator

                    async def observed() -> AsyncIterator[str | bytes | memoryview]:
                        """Forward chunks and close the source before ending request telemetry."""
                        stream_token = correlation_id.set(request_id)
                        failed = False
                        try:
                            with trace.use_span(
                                span, record_exception=False, set_status_on_exception=False
                            ):
                                try:
                                    async for chunk in source:
                                        yield chunk
                                except BaseException as error:
                                    failed = True
                                    emit(
                                        "request_failed",
                                        level=logging.ERROR,
                                        error_type=type(error).__name__,
                                    )
                                    raise
                                finally:
                                    try:
                                        close = getattr(source, "aclose", None)
                                        if close is not None:
                                            await close()
                                    finally:
                                        _finish(span, response.status_code, started, failed)
                        finally:
                            correlation_id.reset(stream_token)

                    response.body_iterator = observed()
                else:
                    _finish(span, response.status_code, started)
                return response
        finally:
            correlation_id.reset(token)

    return wrapped
