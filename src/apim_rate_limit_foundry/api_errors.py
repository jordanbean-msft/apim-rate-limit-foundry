"""Map domain and dependency failures to safe HTTP responses with structured events."""

import logging

from azure.core.exceptions import AzureError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.telemetry import emit


def detail_response(
    status: int, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Build the API's uniform ``{"detail": ...}`` error body."""
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


def _rejected(error_type: str, status: int, error: Exception) -> JSONResponse:
    """Log a client-correctable failure and return its message."""
    emit("request_rejected", level=logging.WARNING, error_type=error_type, http_status=status)
    return detail_response(status, str(error))


async def conflict_handler(request: Request, error: Exception) -> JSONResponse:
    """Return HTTP 409 with a detail string for conflicting domain state."""
    return _rejected("Conflict", 409, error)


async def invalid_handler(request: Request, error: Exception) -> JSONResponse:
    """Return HTTP 400 for a semantically invalid operation or configuration."""
    return _rejected("ValueError", 400, error)


async def unavailable_handler(request: Request, error: Exception) -> JSONResponse:
    """Fail closed with HTTP 503 rather than admitting against missing state."""
    emit(
        "limiter_dependency_unavailable",
        level=logging.ERROR,
        error_type=type(error).__name__,
        http_status=503,
        allowed=False,
    )
    return detail_response(503, "Budget service unavailable; request denied")


async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
    """Return a generic HTTP 500 and correlation ID without exposing internals."""
    return detail_response(
        500,
        "Internal budget service error",
        {"X-Correlation-ID": request.state.correlation_id},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers; the most specific exception class wins during lookup."""
    app.add_exception_handler(Conflict, conflict_handler)
    app.add_exception_handler(ValueError, invalid_handler)
    for error_type in (OSError, AzureError, RedisError):
        app.add_exception_handler(error_type, unavailable_handler)
    app.add_exception_handler(Exception, unexpected_handler)
