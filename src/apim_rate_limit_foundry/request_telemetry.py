import logging
import re
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    correlation_id,
    emit,
    request_correlation,
)

_TRACEPARENT = re.compile(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}\Z")
_ROUTES = frozenset(
    {
        "/api/health",
        "/api/decisions/reserve",
        "/api/decisions/settle",
        "/api/decisions/release",
        "/api/operations/bind",
        "/api/operations/check",
        "/api/reconciliation/recover",
        "/api/usage/summary",
        "/api/{collection}",
        "/api/policies/{record_id}",
        "/api/prices/{record_id}",
        "/api/assignments/{record_id}",
        "/api/{collection}/{record_id}",
    }
)


class RequestTelemetryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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
        if not _TRACEPARENT.fullmatch(traceparent) and invocation is not None:
            traceparent = getattr(invocation, "trace_parent", "") or ""
        carrier = {"traceparent": traceparent} if _TRACEPARENT.fullmatch(traceparent) else {}
        parent = TraceContextTextMapPropagator().extract(carrier) if carrier else None
        started = perf_counter()
        status = 500
        try:
            with trace.get_tracer(LOGGER_NAME).start_as_current_span(
                "limiter.request",
                context=parent,
                kind=SpanKind.SERVER,
                attributes={"correlation_id": correlation_id.get(), "http_method": method},
                record_exception=False,
                set_status_on_exception=False,
            ) as span:

                async def response(message: Message) -> None:
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
                except Exception as error:
                    span.set_attribute("error_type", type(error).__name__)
                    emit("request_failed", level=logging.ERROR, error_type=type(error).__name__)
                    raise
                finally:
                    route = getattr(scope.get("route"), "path", "")
                    route = route if route in _ROUTES else "unmatched"
                    span.update_name(f"{method} {route}")
                    span.set_attribute("route", route)
                    span.set_attribute("http_status", status)
                    span.set_status(StatusCode.ERROR if status >= 500 else StatusCode.OK)
                    emit(
                        "request_completed",
                        level=logging.ERROR if status >= 500 else logging.INFO,
                        http_method=method,
                        route=route,
                        http_status=status,
                        duration_ms=round((perf_counter() - started) * 1000, 3),
                    )
        finally:
            correlation_id.reset(token)
