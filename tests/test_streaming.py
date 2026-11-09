import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from azure.core.exceptions import AzureError
from starlette.requests import Request

from apim_rate_limit_foundry.models.budget_check import BudgetCheck
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.streaming.usage import StreamUsage

STREAM_HOST = Path(__file__).resolve().parents[1] / "stream/function_app.py"


async def test_stream_host_uses_saved_user_context_not_gateway_workload_principal(
    engine, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    await engine.check(
        BudgetCheck(
            request_id="host-stream",
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="application",
            model="model-1",
            api_protocol="openai-chat",
            streaming=True,
        )
    )
    monkeypatch.setattr("apim_rate_limit_foundry.config.Settings", lambda: settings)

    class RuntimeStub:
        def __init__(self, settings):
            self.engine = engine
            self.credential = AsyncMock()

    monkeypatch.setattr("apim_rate_limit_foundry.runtime.Runtime", RuntimeStub)

    async def chunks():
        yield b"data: [DONE]\n\n"

    upstream = AsyncMock(return_value=(200, "text/event-stream", chunks(), {}))
    monkeypatch.setattr(StreamRelay, "_open_upstream", upstream)
    module = runpy.run_path(str(STREAM_HOST))
    handler = module["app"].get_functions()[0].get_user_function()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/stream",
            "headers": [
                (b"x-local-tenant-id", b"tenant-1"),
                (b"x-local-principal-id", b"gateway-managed-identity"),
                (b"x-local-roles", b"RateLimit.Gateway"),
                (b"x-usage-request-id", b"host-stream"),
            ],
        },
        receive=AsyncMock(
            return_value={
                "type": "http.request",
                "body": b'{"model":"model-1","stream":true,"stream_options":{"include_usage":true}}',
            }
        ),
    )

    response = await handler(request)

    assert response.status_code == 200
    upstream.assert_awaited_once()


def test_chat_stream_reads_one_final_cumulative_usage_chunk() -> None:
    observer = StreamUsage("openai-chat")
    for chunk in (
        b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3,"total_tokens":11}}\n\n',
        b"data: [DONE]\n\n",
    ):
        observer.feed(chunk)
    assert observer.finish() == {
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
    }


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_responses_stream_reads_terminal_cumulative_usage(status: str) -> None:
    observer = StreamUsage("openai-responses")
    observer.feed(
        (
            "data: "
            + json.dumps(
                {
                    "type": f"response.{status}",
                    "response": {
                        "status": status,
                        "usage": {"input_tokens": 8, "output_tokens": 3},
                    },
                }
            )
            + "\n\n"
        ).encode()
    )
    assert observer.finish() == {"input_tokens": 8, "output_tokens": 3}


@pytest.mark.parametrize(
    "payload",
    [
        b"data: [DONE]\n\n",
        b'data: {"type":"response.incomplete","response":{"status":"incomplete","usage":{}}}\n\n',
        b'data: {"choices":[],"usage":null}\n\n',
    ],
)
def test_stream_without_trustworthy_terminal_usage_is_unknown(payload: bytes) -> None:
    observer = StreamUsage("openai-chat")
    observer.feed(payload)
    with pytest.raises(ValueError, match="terminal usage"):
        observer.finish()


async def test_event_callback_failure_is_best_effort(
    engine, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = AsyncMock()
    credential.get_token.return_value.token = "managed-identity-token"
    settings.apim_usage_event_url = "https://gateway.example/internal/usage-events"
    settings.api_audience = "api://gateway"
    relay = StreamRelay(engine, credential, settings)

    def fail_session(*args, **kwargs):
        raise aiohttp.ClientConnectionError("private endpoint unavailable")

    monkeypatch.setattr(
        "apim_rate_limit_foundry.streaming.relay.aiohttp.ClientSession", fail_session
    )
    await relay._publish({"event_version": 2, "event_name": "usage_recorded"})
    credential.get_token.assert_awaited_once_with("api://gateway/.default")


@pytest.mark.parametrize("terminal_seen", [True, False])
async def test_client_disconnect_preserves_already_observed_terminal_usage(
    engine, settings, terminal_seen: bool
) -> None:
    await engine.check(
        BudgetCheck(
            request_id="disconnect",
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="application",
            model="model-1",
            api_protocol="openai-chat",
            streaming=True,
        )
    )

    async def chunks(size):
        if terminal_seen:
            yield b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n\n'
        else:
            yield b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n'

    response = SimpleNamespace(content=SimpleNamespace(iter_chunked=chunks), close=Mock())
    session = SimpleNamespace(close=AsyncMock())
    relay = StreamRelay(engine, AsyncMock(), settings)
    relay._publish = AsyncMock()
    stream = relay._stream("disconnect", "openai-chat", response, session)

    await anext(stream)
    await stream.aclose()

    records = await engine.repository.list("usage_v2")
    assert len(records) == 1
    usage = records[0]["data"]
    assert usage["status"] == ("actual" if terminal_seen else "usage_unknown")
    assert usage["input_tokens"] == (8 if terminal_seen else None)
    relay._publish.assert_awaited_once()


async def test_callback_identity_failure_does_not_fail_completed_inference(
    engine, settings
) -> None:
    credential = AsyncMock()
    credential.get_token.side_effect = AzureError("private credential detail")
    settings.apim_usage_event_url = "https://gateway.example/internal/usage-events"
    settings.api_audience = "api://gateway"
    relay = StreamRelay(engine, credential, settings)

    await relay._publish({"event_version": 2, "event_name": "usage_recorded"})

    credential.get_token.assert_awaited_once_with("api://gateway/.default")


async def test_relay_preserves_incremental_chunks_and_records_terminal_usage(
    engine, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployment = ModelDeployment(
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
    settings.model_registry = {"openai-chat:model-1": deployment}
    await engine.check(
        BudgetCheck(
            request_id="stream-request",
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="apim-app",
            model="model-1",
            api_protocol="openai-chat",
            streaming=True,
        )
    )
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3,"total_tokens":11}}\n\n',
        b"data: [DONE]\n\n",
    ]

    class Content:
        async def iter_chunked(self, size):
            for chunk in chunks:
                yield chunk

    class Response:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "text/event-stream"}
            self.content = Content()

        def close(self):
            pass

    class Session:
        async def post(self, *args, **kwargs):
            return Response()

        async def close(self):
            pass

    session = Session()
    monkeypatch.setattr(
        "apim_rate_limit_foundry.streaming.relay.aiohttp.ClientSession",
        lambda **kwargs: session,
    )
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(token="managed-identity-token")
    relay = StreamRelay(engine, credential, settings)
    relay._publish = AsyncMock()
    body = json.dumps(
        {
            "model": "model-1",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()

    status, content_type, response_chunks, _ = await relay.open("tenant-1", "stream-request", body)
    delivered = [chunk async for chunk in response_chunks]

    assert status == 200 and content_type == "text/event-stream"
    assert delivered == chunks
    records = await engine.repository.list("usage_v2")
    assert len(records) == 1
    assert records[0]["data"]["status"] == "actual"
    assert records[0]["data"]["input_tokens"] == 8
    relay._publish.assert_awaited_once()
    with pytest.raises(ValueError, match="Completed request"):
        await relay.open("tenant-1", "stream-request", body)
