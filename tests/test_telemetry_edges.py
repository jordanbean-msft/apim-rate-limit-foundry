import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.request_telemetry import RequestTelemetryMiddleware
from apim_rate_limit_foundry.stores.memory import MemoryRepository
from apim_rate_limit_foundry.streaming.request_telemetry import trace_stream_request
from apim_rate_limit_foundry.telemetry import safe_attributes


def post() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/stream", "headers": []})


async def test_non_http_scopes_bypass_request_telemetry() -> None:
    app = AsyncMock()
    scope = {"type": "lifespan"}

    await RequestTelemetryMiddleware(app)(scope, AsyncMock(), AsyncMock())

    app.assert_awaited_once()
    assert "state" not in scope


async def test_buffered_stream_host_replies_are_traced_and_tagged_with_a_correlation_id() -> None:
    @trace_stream_request
    async def handler(req: Request) -> JSONResponse:
        return JSONResponse({"detail": "conflict"}, status_code=409)

    response = await handler(post())

    assert response.status_code == 409
    assert response.headers["X-Correlation-ID"]


async def test_handler_failures_propagate_after_telemetry() -> None:
    @trace_stream_request
    async def handler(req: Request) -> JSONResponse:
        raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        await handler(post())


async def test_stream_failures_are_reported_and_the_source_is_closed() -> None:
    closed = asyncio.Event()

    async def chunks():
        try:
            yield b"first"
            raise OSError("provider reset")
        finally:
            closed.set()

    @trace_stream_request
    async def handler(req: Request) -> StreamingResponse:
        return StreamingResponse(chunks())

    response = await handler(post())
    received = []
    with pytest.raises(OSError, match="provider reset"):
        async for chunk in response.body_iterator:
            received.append(chunk)

    assert received == [b"first"] and closed.is_set()


def test_telemetry_attributes_drop_unsafe_subscription_and_streaming_values() -> None:
    attributes = safe_attributes(
        {
            "subscription_id": "../secret",
            "streaming": "yes",
            "model": "*",
            "budget_model": "*",
            "month": "2030-01",
        }
    )

    assert attributes == {"model": "*", "budget_model": "*", "month": "2030-01"}


async def test_an_unexpectedly_failed_background_worker_is_reported(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("apim_rate_limit_foundry"), "propagate", True)

    async def failing() -> None:
        raise RuntimeError("worker crashed")

    task = asyncio.create_task(failing())
    await asyncio.gather(task, return_exceptions=True)
    caplog.set_level("ERROR", logger="apim_rate_limit_foundry")

    BackgroundWriter._completed(task)

    assert "background_worker_failed" in caplog.text


@pytest.mark.parametrize("operation", ["get", "list", "create", "mutate"])
async def test_memory_repository_simulates_a_durable_outage(operation: str) -> None:
    repository = MemoryRepository()
    repository.fail = True
    calls = {
        "get": lambda: repository.get("budgets", "b"),
        "list": lambda: repository.list("budgets"),
        "create": lambda: repository.create("budgets", "b", {"id": "b"}),
        "mutate": lambda: repository.mutate("budgets", "b", None, {"id": "a"}),
    }

    with pytest.raises(OSError, match="Injected durable storage failure"):
        await calls[operation]()
