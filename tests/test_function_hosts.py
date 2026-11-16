import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import azure.functions as func
import pytest
from starlette.requests import Request

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.streaming.relay import StreamRelay

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = {
    "x-local-tenant-id": "tenant-1",
    "x-local-principal-id": "gateway",
    "x-local-roles": "RateLimit.Gateway",
    "x-usage-request-id": "stream-1",
}


def test_api_host_exposes_the_asgi_app_anonymously_behind_easy_auth() -> None:
    module = runpy.run_path(str(ROOT / "function_app.py"))

    assert isinstance(module["app"], func.AsgiFunctionApp)
    assert module["api"].title == "AI Monthly Budget Gateway"


def stream_request(headers: dict[str, str], body: bytes = b"{}") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/stream",
            "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
        },
        receive=AsyncMock(return_value={"type": "http.request", "body": body}),
    )


@pytest.fixture
def host(settings: Settings, engine, monkeypatch: pytest.MonkeyPatch):
    settings.stream_max_body_bytes = 1024
    state = SimpleNamespace(credential=AsyncMock())

    class RuntimeStub:
        def __init__(self, configured: Settings) -> None:
            self.engine = engine
            self.credential = state.credential

        def http_session(self) -> object:
            return object()

    monkeypatch.setattr("apim_rate_limit_foundry.config.Settings", lambda: settings)
    monkeypatch.setattr("apim_rate_limit_foundry.runtime.Runtime", RuntimeStub)
    module = runpy.run_path(str(ROOT / "stream/function_app.py"))
    handler = module["app"].get_functions()[0].get_user_function()
    return SimpleNamespace(handler=handler, state=state)


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({}, b"{}", 401),
        ({**GATEWAY, "x-local-roles": "RateLimit.Reader"}, b"{}", 403),
        ({k: v for k, v in GATEWAY.items() if k != "x-usage-request-id"}, b"{}", 400),
        (GATEWAY, b"x" * 2048, 413),
    ],
)
async def test_stream_host_rejects_unauthorized_or_malformed_requests(
    host: SimpleNamespace, headers: dict[str, str], body: bytes, status: int
) -> None:
    response = await host.handler(stream_request(headers, body))

    assert response.status_code == status


async def test_stream_host_requires_a_managed_identity_for_provider_calls(
    host: SimpleNamespace,
) -> None:
    host.state.credential = None

    response = await host.handler(stream_request(GATEWAY))

    assert response.status_code == 503


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValueError("bad model"), 409),
        (Conflict("not admitted"), 409),
        (OSError("redis offline"), 503),
    ],
)
async def test_stream_host_translates_relay_failures_without_leaking_details(
    host: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(StreamRelay, "open", AsyncMock(side_effect=error))

    response = await host.handler(stream_request(GATEWAY))

    assert response.status_code == status
    assert str(error).encode() not in response.body
