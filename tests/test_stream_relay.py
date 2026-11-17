import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.models.budget_check import BudgetCheck
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from tests.fakes import FakeHttpSession

BODY = {"model": "model-1", "stream": True, "stream_options": {"include_usage": True}}


def encode(**changes: object) -> bytes:
    return json.dumps({**BODY, **changes}).encode()


@pytest.fixture
def relay(gateway: GatewayServices, settings: Settings) -> StreamRelay:
    settings.model_registry = {
        "openai-chat:model-1": ModelDeployment(
            api_protocol="openai-chat",
            endpoint="https://models.example.com",
            path="/openai/deployments/model-1/chat/completions",
            model="model-1",
            audience="https://cognitiveservices.azure.com",
            api_version="2025-01-01-preview",
            price_version="v1",
            max_input_tokens=100,
            max_output_tokens=20,
        )
    }
    return StreamRelay(gateway, AsyncMock(), settings, FakeHttpSession())


async def admit(
    gateway: GatewayServices, request_id: str = "stream-1", streaming: bool = True
) -> None:
    await gateway.admission.check(
        BudgetCheck(
            request_id=request_id,
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="application",
            model="model-1",
            api_protocol="openai-chat",
            streaming=streaming,
        )
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"x" * 200_000, "exceeds bound"),
        (b"{not json", "Invalid streaming request body"),
        (b"\xff\xfe", "Invalid streaming request body"),
        (b"[1]", "streaming OpenAI request is required"),
        (json.dumps({"model": "model-1"}).encode(), "streaming OpenAI request is required"),
    ],
)
async def test_open_rejects_malformed_or_non_streaming_bodies(
    relay: StreamRelay, body: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await relay.open("tenant-1", "stream-1", body)


async def test_open_requires_an_allowed_streaming_admission_for_the_same_tenant(
    relay: StreamRelay, gateway: GatewayServices
) -> None:
    with pytest.raises(Conflict, match="admitted budget check"):
        await relay.open("tenant-1", "never-admitted", encode())

    await admit(gateway, "stream-1")
    with pytest.raises(Conflict, match="admitted budget check"):
        await relay.open("tenant-2", "stream-1", encode())

    await admit(gateway, "buffered-1", streaming=False)
    with pytest.raises(Conflict, match="admitted stream request"):
        await relay.open("tenant-1", "buffered-1", encode())


async def test_open_rejects_admissions_that_were_denied(
    relay: StreamRelay, gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await admit(gateway, "stream-1")
    denied = await gateway.counters.request("stream-1")
    denied["data"]["decision"]["allowed"] = False
    monkeypatch.setattr(gateway.counters, "request", AsyncMock(return_value=denied))

    with pytest.raises(Conflict, match="admitted stream request"):
        await relay.open("tenant-1", "stream-1", encode())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (encode(model="another-deployment"), "does not match"),
        (encode(stream_options={}), "include_usage"),
        (encode(stream_options="yes"), "include_usage"),
        (json.dumps({"model": "model-1", "stream": True}).encode(), "include_usage"),
    ],
)
async def test_open_pins_the_admitted_model_and_requires_chat_usage(
    relay: StreamRelay, gateway: GatewayServices, body: bytes, message: str
) -> None:
    await admit(gateway)

    with pytest.raises(ValueError, match=message):
        await relay.open("tenant-1", "stream-1", body)


def upstream_reply(status: int, content_type: str, chunks: list[bytes]) -> SimpleNamespace:
    async def iter_chunked(size: int):
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(
        status=status,
        headers={"Content-Type": content_type},
        content=SimpleNamespace(iter_chunked=iter_chunked),
        close=Mock(),
    )


@pytest.mark.parametrize(
    ("reply", "expected_status", "expected_body", "charged"),
    [
        (
            upstream_reply(500, "application/json", [b"x" * 70_000]),
            500,
            b"provider_stream_unavailable",
            False,
        ),
        (
            upstream_reply(502, "text/html", [b"<h1>bad gateway</h1>"]),
            502,
            b"provider_stream_unavailable",
            False,
        ),
        (upstream_reply(200, "application/json", [b'{"ok":1}']), 502, b'{"ok":1}', True),
    ],
)
async def test_unusable_provider_replies_become_bounded_errors_charged_only_when_ok(
    gateway: GatewayServices,
    settings: Settings,
    reply: SimpleNamespace,
    expected_status: int,
    expected_body: bytes,
    charged: bool,
) -> None:
    await admit(gateway)
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(token="token")
    relay = StreamRelay(gateway, credential, settings, FakeHttpSession(lambda url, **kw: reply))
    backend = ModelDeployment(
        api_protocol="openai-chat",
        endpoint="https://models.example.com",
        path="/openai/deployments/model-1/chat/completions",
        model="model-1",
        audience="https://cognitiveservices.azure.com",
        price_version="v1",
        max_input_tokens=100,
        max_output_tokens=20,
    )

    status, content_type, body, _ = await relay._open_upstream(
        "stream-1", backend, "openai-chat", b"{}"
    )

    assert (status, content_type) == (expected_status, "application/json")
    assert expected_body in b"".join([chunk async for chunk in body])
    reply.close.assert_called_once()
    recorded = await gateway.counters.usage("stream-1")
    assert (recorded["data"]["status"] == "usage_unknown") if charged else recorded is None
