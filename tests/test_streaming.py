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
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.streaming.usage import StreamUsage
from tests.fakes import FakeHttpSession, persisted_usage

# Host-wide default ceilings (131072 input, 32768 output) at the fixture's 2/4 USD per million.
UPPER_BOUND = 131072 * 2 + 32768 * 4
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

        def http_session(self):
            return FakeHttpSession()

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
    assert [chunk async for chunk in response.body_iterator] == [b"data: [DONE]\n\n"]
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


async def test_event_callback_failure_is_best_effort(engine, settings) -> None:
    credential = AsyncMock()
    credential.get_token.return_value.token = "managed-identity-token"
    settings.apim_usage_event_url = "https://gateway.example/internal/usage-events"
    settings.api_audience = "api://gateway"

    def unavailable(url, **kwargs):
        raise aiohttp.ClientConnectionError("private endpoint unavailable")

    relay = StreamRelay(engine, credential, settings, FakeHttpSession(unavailable))

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
    session = FakeHttpSession()
    relay = StreamRelay(engine, AsyncMock(), settings, session)
    relay._publish = AsyncMock()
    stream = relay._stream("disconnect", "openai-chat", response)

    await anext(stream)
    await stream.aclose()

    await engine.background.flush()
    records = await persisted_usage(engine)
    assert len(records) == 1
    usage = records[0]["data"]
    assert usage["status"] == ("actual" if terminal_seen else "usage_unknown")
    assert usage["input_tokens"] == (8 if terminal_seen else None)
    assert usage["cost_basis"] == ("provider_usage" if terminal_seen else "estimated_upper_bound")
    assert usage["cost_micro_usd"] == (28 if terminal_seen else UPPER_BOUND)
    response.close.assert_called_once()
    session.close.assert_not_awaited()
    relay._publish.assert_awaited_once()


async def test_callback_identity_failure_does_not_fail_completed_inference(
    engine, settings
) -> None:
    credential = AsyncMock()
    credential.get_token.side_effect = AzureError("private credential detail")
    settings.apim_usage_event_url = "https://gateway.example/internal/usage-events"
    settings.api_audience = "api://gateway"
    relay = StreamRelay(engine, credential, settings, FakeHttpSession())

    await relay._publish({"event_version": 2, "event_name": "usage_recorded"})

    credential.get_token.assert_awaited_once_with("api://gateway/.default")


async def test_relay_preserves_incremental_chunks_and_records_terminal_usage(
    engine, settings
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

    session = FakeHttpSession(lambda url, **kwargs: Response())
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(token="managed-identity-token")
    relay = StreamRelay(engine, credential, settings, session)
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
    await engine.background.flush()
    records = await persisted_usage(engine)
    assert len(records) == 1
    assert records[0]["data"]["status"] == "actual"
    assert records[0]["data"]["input_tokens"] == 8
    relay._publish.assert_awaited_once()
    with pytest.raises(ValueError, match="Completed request"):
        await relay.open("tenant-1", "stream-request", body)


def responses_terminal(output_bytes: int, status: str = "completed", **extra: object) -> bytes:
    event = {
        "type": f"response.{status}",
        "sequence_number": 7,
        "status": "ignored",
        "usage": {"input_tokens": 999},
        "response": {
            "id": "resp_1",
            "status": status,
            "output": [{"type": "message", "text": 'quote " \\ ' + "x" * output_bytes}],
            "usage": {
                "input_tokens": 8,
                "output_tokens": 3,
                "input_tokens_details": {"cached_tokens": 2},
            },
            "metadata": {"status": "ignored", "usage": {"input_tokens": 999}},
            **extra,
        },
    }
    return (
        b"event: response." + status.encode() + b"\ndata: " + json.dumps(event).encode() + b"\n\n"
    )


@pytest.mark.parametrize("chunk_size", [None, 1, 4096, 70000])
@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_responses_terminal_event_above_the_bound_still_yields_usage(
    chunk_size: int | None, status: str
) -> None:
    payload = responses_terminal(300_000, status)
    observer = StreamUsage("openai-responses", max_event_bytes=65536)

    step = chunk_size or len(payload)
    for start in range(0, len(payload), step):
        observer.feed(payload[start : start + step])
        assert len(observer.buffer) <= 65536

    assert observer.finish() == {
        "input_tokens": 8,
        "output_tokens": 3,
        "input_tokens_details": {"cached_tokens": 2},
    }


def test_oversized_nonterminal_responses_event_is_discarded() -> None:
    delta = {"type": "response.output_text.delta", "delta": "y" * 200_000}
    observer = StreamUsage("openai-responses", max_event_bytes=65536)
    observer.feed(b"data: " + json.dumps(delta).encode() + b"\r\n\r\n")
    observer.feed(responses_terminal(10))
    assert observer.finish()["output_tokens"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        b'data: {"type":"response.completed","response":{"status":"completed","output":"'
        + b"z" * 100_000
        + b'"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"failed","usage":{},"output":"'
        + b"z" * 100_000
        + b'"}}\n\n',
        b'data: {"error":{},"type":"response.completed","response":{"output":"'
        + b"z" * 100_000
        + b'"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed","usage":{"a":"'
        + b"u" * 100_000
        + b'"}}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed","output":"'
        + b"z" * 100_000
        + b'","usage":{}}}} \n\n',
    ],
)
def test_oversized_terminal_event_without_trustworthy_usage_is_unknown(payload: bytes) -> None:
    observer = StreamUsage("openai-responses", max_event_bytes=65536)
    observer.feed(payload)
    with pytest.raises(ValueError, match="terminal usage"):
        observer.finish()


def test_oversized_chat_event_and_truncated_oversized_event_are_unknown() -> None:
    chat = StreamUsage("openai-chat", max_event_bytes=65536)
    chat.feed(b'data: {"choices":[{"delta":{"content":"' + b"c" * 100_000 + b'"}}]}\n\n')
    with pytest.raises(ValueError, match="terminal usage"):
        chat.finish()

    truncated = StreamUsage("openai-responses", max_event_bytes=65536)
    truncated.feed(b'data: {"type":"response.completed","response":{"output":"' + b"c" * 100_000)
    with pytest.raises(ValueError, match="terminal usage"):
        truncated.finish()


async def test_oversized_responses_stream_is_priced_from_its_real_usage(engine, settings) -> None:
    await engine.check(
        BudgetCheck(
            request_id="large-response",
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="application",
            model="model-1",
            api_protocol="openai-responses",
            streaming=True,
        )
    )
    payload = responses_terminal(200_000)

    async def chunks(size):
        for start in range(0, len(payload), size):
            yield payload[start : start + size]

    response = SimpleNamespace(content=SimpleNamespace(iter_chunked=chunks), close=Mock())
    relay = StreamRelay(engine, AsyncMock(), settings, FakeHttpSession())
    relay._publish = AsyncMock()

    delivered = b"".join(
        [chunk async for chunk in relay._stream("large-response", "openai-responses", response)]
    )

    assert delivered == payload
    await engine.background.flush()
    usage = (await persisted_usage(engine))[0]["data"]
    assert usage["status"] == "actual"
    assert (usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]) == (
        8,
        2,
        3,
    )
    assert usage["cost_micro_usd"] == 6 * 2 + 2 * 0.5 + 3 * 4


async def test_upstream_error_mid_stream_charges_the_upper_bound_once(engine, settings) -> None:
    await engine.check(
        BudgetCheck(
            request_id="broken",
            tenant_id="tenant-1",
            principal_id="user-1",
            subscription_id="application",
            model="model-1",
            api_protocol="openai-chat",
            streaming=True,
        )
    )

    async def chunks(size):
        yield b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n'
        raise aiohttp.ClientPayloadError("connection reset")

    response = SimpleNamespace(content=SimpleNamespace(iter_chunked=chunks), close=Mock())
    relay = StreamRelay(engine, AsyncMock(), settings, FakeHttpSession())
    relay._publish = AsyncMock()

    assert len([c async for c in relay._stream("broken", "openai-chat", response)]) == 1

    await engine.background.flush()
    usage = (await persisted_usage(engine))[0]["data"]
    assert usage["status"] == "usage_unknown"
    assert usage["cost_micro_usd"] == UPPER_BOUND
    assert not (await engine.check(stream_check("next")))["allowed"]


def stream_check(request_id: str) -> BudgetCheck:
    return BudgetCheck(
        request_id=request_id,
        tenant_id="tenant-1",
        principal_id="user-1",
        subscription_id="application",
        model="model-1",
        api_protocol="openai-chat",
        streaming=True,
    )


async def test_failed_final_accounting_is_logged_not_raised(engine, settings) -> None:
    async def chunks(size):
        yield b"data: [DONE]\n\n"

    response = SimpleNamespace(content=SimpleNamespace(iter_chunked=chunks), close=Mock())
    relay = StreamRelay(engine, AsyncMock(), settings, FakeHttpSession())
    relay._record = AsyncMock(side_effect=AzureError("redis down"))

    assert [c async for c in relay._stream("missing", "openai-chat", response)] == [
        b"data: [DONE]\n\n"
    ]
    relay._record.assert_awaited_once_with("missing", "usage_unknown", None)


async def test_runtime_shares_and_closes_one_http_session(settings) -> None:
    runtime = Runtime(settings)
    session = runtime.http_session()

    assert runtime.http_session() is session
    await runtime.close()
    assert session.closed


def test_stream_host_builds_one_cached_runtime_without_module_state(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = []

    class RuntimeStub:
        def __init__(self, configured):
            built.append(configured)

    monkeypatch.setattr("apim_rate_limit_foundry.config.Settings", lambda: settings)
    monkeypatch.setattr("apim_rate_limit_foundry.runtime.Runtime", RuntimeStub)
    module = runpy.run_path(str(STREAM_HOST))

    assert module["get_runtime"]() is module["get_runtime"]()
    assert built == [settings]
    assert "runtime" not in module


def backend() -> ModelDeployment:
    return ModelDeployment(
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


async def test_provider_open_failure_is_charged_the_upper_bound_on_the_shared_session(
    engine, settings
) -> None:
    await engine.check(stream_check("open-fails"))
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(token="token")

    def unavailable(url, **kwargs):
        raise aiohttp.ClientConnectionError("provider down")

    session = FakeHttpSession(unavailable)
    relay = StreamRelay(engine, credential, settings, session)
    relay._publish = AsyncMock()

    with pytest.raises(aiohttp.ClientConnectionError):
        await relay._open_upstream("open-fails", backend(), "openai-chat", b"{}")

    await engine.background.flush()
    usage = (await persisted_usage(engine))[0]["data"]
    assert usage["status"] == "usage_unknown"
    assert usage["cost_micro_usd"] == UPPER_BOUND
    session.close.assert_not_awaited()
    assert session.calls[0][1]["timeout"].total == settings.stream_timeout_seconds


async def test_provider_error_reply_is_bounded_json_and_charged_the_upper_bound(
    engine, settings
) -> None:
    await engine.check(stream_check("provider-429"))
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(token="token")

    class Body:
        async def iter_chunked(self, size):
            yield b'{"error":"slow down"}'

    response = SimpleNamespace(
        status=429,
        headers={"Content-Type": "application/json", "Retry-After": "7"},
        content=Body(),
        close=Mock(),
    )
    relay = StreamRelay(engine, credential, settings, FakeHttpSession(lambda url, **kw: response))
    relay._publish = AsyncMock()

    status, content_type, body, headers = await relay._open_upstream(
        "provider-429", backend(), "openai-chat", b"{}"
    )

    assert (status, content_type, headers) == (429, "application/json", {"Retry-After": "7"})
    assert [chunk async for chunk in body] == [b'{"error":"slow down"}']
    response.close.assert_called_once()
    await engine.background.flush()
    assert (await persisted_usage(engine))[0]["data"]["cost_micro_usd"] == UPPER_BOUND
