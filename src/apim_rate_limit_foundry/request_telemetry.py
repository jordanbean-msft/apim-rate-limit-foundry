"""ASGI request timing/correlation without body, query-string or identity capture."""

import logging
from time import perf_counter

from opentelemetry.trace import Span, SpanKind, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.telemetry import (
    correlation_id,
    elapsed_ms,
    emit,
    get_tracer,
    request_correlation,
    request_trace_context,
)


def finish_request(
    span: Span, method: str, route: str, status: int, started: float, failed: bool = False
) -> None:
    """Record one request's span attributes, outcome metric and completion event.

    Budget/auth rejections (4xx) are client outcomes; only 5xx or an escaped
    exception is an error. The caller owns span lifetime.
    """
    failed = failed or status >= 500
    outcome = "error" if failed else "rejected" if status >= 400 else "ok"
    duration_ms = elapsed_ms(started)
    span.update_name(f"{method} {route}")
    span.set_attribute("route", route)
    span.set_attribute("http.route", route)
    span.set_attribute("http_status", status)
    span.set_attribute("http.response.status_code", status)
    span.set_status(StatusCode.ERROR if failed else StatusCode.OK)
    rate_metrics.request(method, route, status, duration_ms, outcome)
    emit(
        "request_completed",
        level=logging.ERROR if failed else logging.INFO,
        http_method=method,
        route=route,
        http_status=status,
        duration_ms=duration_ms,
        status=outcome,
    )


class RequestTelemetryMiddleware:
    """Emit one safe server span and outcome per HTTP request, including rejections."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Propagate a validated parent trace and attach a sanitized correlation ID.

        HTTP response status is observed as ASGI messages pass through. Route names
        are replaced by known templates only after routing, avoiding raw record IDs
        and unbounded paths in telemetry. Non-HTTP ASGI messages pass through.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        incoming = headers.get(b"x-correlation-id", b"").decode("latin-1")
        token = correlation_id.set(request_correlation(incoming))
        scope.setdefault("state", {})["correlation_id"] = correlation_id.get()
        method = scope.get("method", "")
        method = (
            method
            if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
            else "OTHER"
        )
        traceparent = headers.get(b"traceparent", b"").decode("latin-1")
        # Functions passes invocation tracing_context through its ASGI adapter.
        invocation = scope.get("azure_functions.trace_context")
        if request_trace_context(traceparent) is None and invocation is not None:
            traceparent = getattr(invocation, "trace_parent", "") or ""
        parent = request_trace_context(traceparent)
        started = perf_counter()
        status = 500
        failed = False
        try:
            with get_tracer().start_as_current_span(
                "limiter.request",
                context=parent,
                kind=SpanKind.SERVER,
                attributes={
                    "correlation_id": correlation_id.get(),
                    "http_method": method,
                    "http.request.method": method,
                },
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                emit("request_started", http_method=method)

                async def response(message: Message) -> None:
                    """Capture status and replace any downstream correlation header."""
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                        response_headers = [
                            (key, value)
                            for key, value in message.get("headers", [])
                            if key.lower() != b"x-correlation-id"
                        ]
                        message["headers"] = [
                            *response_headers,
                            (b"x-correlation-id", correlation_id.get().encode("ascii")),
                        ]
                    await send(message)

                try:
                    await self.app(scope, receive, response)
                except BaseException as error:
                    failed = True
                    span.set_attribute("error_type", type(error).__name__)
                    emit("request_failed", level=logging.ERROR, error_type=type(error).__name__)
                    raise
                finally:
                    # Templates exist only for matched routes, so paths stay low-cardinality.
                    route = getattr(scope.get("route"), "path", "") or "unmatched"
                    finish_request(span, method, route, status, started, failed)
        finally:
            # A worker handles concurrent requests; never leak one ID into the next task.
            correlation_id.reset(token)
