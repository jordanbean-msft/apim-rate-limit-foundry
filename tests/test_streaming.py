import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from azure.core.credentials import AccessToken

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.fingerprints import reserve_fingerprint
from apim_rate_limit_foundry.models import Price, Reserve
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.stream_backend import StreamBackend
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.streaming import relay as relay_module
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.streaming.replay import replay_stream_usage
from apim_rate_limit_foundry.streaming.usage import StreamUsage


def sse(data: dict | str) -> bytes:
    value = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {value}\n\n".encode()


def events(protocol: str) -> bytes:
    if protocol == "openai-chat":
        return (
            sse({"choices": [{"delta": {"content": "Hello"}}]})
            + sse(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "prompt_tokens_details": {"cached_tokens": 8},
                    },
                }
            )
            + sse("[DONE]")
        )
    if protocol == "openai-responses":
        return sse({"type": "response.output_text.delta", "delta": "Hello"}) + sse(
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "input_tokens_details": {"cached_tokens": 8},
                    },
                },
            }
        )
    return (
        sse(
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 8,
                        "cache_creation_input_tokens": 0,
                    }
                },
            }
        )
        + sse({"type": "content_block_delta", "delta": {"text": "Hello"}})
        + sse({"type": "message_delta", "usage": {"output_tokens": 5}})
        + sse({"type": "message_stop"})
    )


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic-messages"])
@pytest.mark.parametrize("chunk_size", [1, 7, 8192])
def test_usage_is_incremental_for_all_protocols(protocol: str, chunk_size: int) -> None:
    observer = StreamUsage(protocol)
    wire = events(protocol).replace(b"\n", b"\r\n")
    for offset in range(0, len(wire), chunk_size):
        observer.feed(wire[offset : offset + chunk_size])
    assert (
        observer.finish()["output_tokens" if protocol != "openai-chat" else "completion_tokens"]
        == 5
    )


@pytest.mark.parametrize(
    "wire",
    [
        sse("[DONE]"),
        events("openai-chat").replace(b"data: [DONE]\n\n", b""),
        events("openai-chat") + sse({"error": {"message": "provider failure"}}),
        sse({"choices": [], "usage": {}}) * 2 + sse("[DONE]"),
        b"data: invalid json\n\n",
        b"data: \xff\n\n",
        sse({"type": "message_stop"}),
    ],
)
def test_bad_streams_cannot_produce_actual_usage(wire: bytes) -> None:
    observer = StreamUsage("openai-chat")
    observer.feed(wire)
    with pytest.raises(ValueError):
        observer.finish()


def test_oversized_events_stop_observation_without_retaining_content() -> None:
    observer = StreamUsage("openai-chat", max_event_bytes=128)
    observer.feed(b"data: " + b"x" * 129)
    assert observer.invalid and not observer.buffer and not observer.lines
    observer.feed(events("openai-chat"))
    with pytest.raises(ValueError):
        observer.finish()


class Credential:
    async def get_token(self, *scopes: str) -> AccessToken:
        assert scopes == ("https://cognitiveservices.azure.com/.default",)
        return AccessToken("test-provider-token", 9999999999)


async def admitted(
    engine: Engine, settings: Settings, request_body: Reserve, protocol: str = "openai-chat"
) -> tuple[StreamRelay, str, bytes]:
    body = json.dumps(
        {
            "model": request_body.model,
            "stream": True,
            "max_tokens": 20,
            **({"stream_options": {"include_usage": True}} if protocol == "openai-chat" else {}),
        }
    ).encode()
    request = request_body.model_copy(
        update={
            "streaming": True,
            "api_protocol": protocol,
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }
    )
    if protocol == "anthropic-messages":
        price = (await engine.configuration("prices"))[0]
        await engine.repository.mutate(
            "prices",
            price["id"],
            {**price, "cache_write_5m_per_million": "2", "cache_write_1h_per_million": "2"},
            {"id": "stream-test-cache-prices"},
        )
    decision = await engine.reserve(request)
    assert decision.allowed
    settings.stream_backends[protocol] = StreamBackend(
        endpoint="https://example.openai.azure.com",
        path="/provider",
        model=request.model,
        audience="https://cognitiveservices.azure.com",
    )
    return StreamRelay(engine, Credential(), settings), decision.reservation_id, body


class Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def iter_chunked(self, size: int):
        for chunk in self.chunks:
            yield chunk


class Response:
    def __init__(self, wire: bytes) -> None:
        self.content = Content([wire[:20], wire[20:]])
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic-messages"])
async def test_trusted_streams_settle_cached_actual_cost(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    protocol: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body, protocol)
    observed_events: list[tuple[str, dict]] = []

    def capture(event_name: str, **attributes: object) -> None:
        observed_events.append((event_name, attributes))

    monkeypatch.setattr(relay_module, "emit", capture)
    request, _ = await relay.claim(reservation_id, body)
    wire = events(protocol)
    response, session = Response(wire), AsyncMock()
    forwarded = b"".join(
        [chunk async for chunk in relay._stream(request, reservation_id, response, session)]
    )
    assert forwarded == wire
    actual = await engine.repository.get("settlements", reservation_id)
    assert actual["data"]["cost_micro_usd"] == 28
    assert actual["data"]["usage"]["cached_input_tokens"] == 8
    assert not actual["data"]["estimated"]
    assert sorted(engine.counters.counts.values()) == [28]
    assert await engine.repository.get("stream_usage", reservation_id)
    assert {name for name, _ in observed_events} == {
        "stream_dispatch_started",
        "stream_usage_observed",
        "stream_settlement_completed",
    }
    assert all(
        attributes["subscription_id"] == request_body.subscription_id
        and attributes["application_name"] == request_body.subscription_id
        for _, attributes in observed_events
    )
    assert response.closed
    session.close.assert_awaited_once()


@pytest.mark.parametrize(
    "wire",
    [
        sse({"choices": [{"delta": {"content": "Hello"}}]}),
        events("openai-chat").replace(b'"completion_tokens": 5', b'"completion_tokens": 21'),
        events("openai-chat").replace(b'"cached_tokens": 8', b'"cached_tokens": 11'),
    ],
)
async def test_missing_or_out_of_bound_usage_keeps_reservation(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    wire: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    observed_events: list[tuple[str, dict]] = []

    def capture(event_name: str, **attributes: object) -> None:
        observed_events.append((event_name, attributes))

    monkeypatch.setattr(relay_module, "emit", capture)
    request, _ = await relay.claim(reservation_id, body)
    async for _ in relay._stream(request, reservation_id, Response(wire), AsyncMock()):
        pass
    assert await engine.repository.get("settlements", reservation_id) is None
    assert await engine.repository.get("stream_usage", reservation_id) is None
    assert sorted(engine.counters.counts.values()) == [100]
    pending = await engine.repository.get("reconciliation", f"stream-{reservation_id}")
    assert pending["data"]["estimated"]
    pending_event = next(
        attributes for name, attributes in observed_events if name == "stream_settlement_pending"
    )
    assert pending_event["subscription_id"] == request_body.subscription_id


async def test_disconnect_cannot_refund_or_dispatch_again(
    engine: Engine, settings: Settings, request_body: Reserve
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    request, _ = await relay.claim(reservation_id, body)
    stream = relay._stream(request, reservation_id, Response(events("openai-chat")), AsyncMock())
    await anext(stream)
    await stream.aclose()
    assert await engine.repository.get("settlements", reservation_id) is None
    assert sorted(engine.counters.counts.values()) == [100]
    with pytest.raises(Conflict, match="dispatched"):
        await relay.claim(reservation_id, body)


async def test_claim_requires_exact_body_and_only_one_dispatch(
    engine: Engine, settings: Settings, request_body: Reserve
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    with pytest.raises(Conflict, match="body"):
        await relay.claim(reservation_id, body + b" ")
    results = await asyncio.gather(
        relay.claim(reservation_id, body), relay.claim(reservation_id, body), return_exceptions=True
    )
    assert sum(isinstance(result, Conflict) for result in results) == 1


async def test_trusted_evidence_replays_after_settlement_failure(
    engine: Engine, settings: Settings, request_body: Reserve, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    request, _ = await relay.claim(reservation_id, body)
    real_settle = engine.settle
    monkeypatch.setattr(engine, "settle", AsyncMock(side_effect=OSError("temporary dependency")))
    async for _ in relay._stream(
        request, reservation_id, Response(events("openai-chat")), AsyncMock()
    ):
        pass
    assert await engine.repository.get("stream_usage", reservation_id)
    assert sorted(engine.counters.counts.values()) == [100]
    monkeypatch.setattr(engine, "settle", real_settle)
    assert await replay_stream_usage(engine) == 1
    assert await replay_stream_usage(engine) == 0
    assert sorted(engine.counters.counts.values()) == [28]


@pytest.mark.parametrize("provider_status", [200, 429])
async def test_relay_delivers_first_provider_bytes_before_terminal_usage(
    engine: Engine, settings: Settings, request_body: Reserve, provider_status: int
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    release = asyncio.Event()
    first = sse({"choices": [{"delta": {"content": "first"}}]})

    async def provider(request: web.Request) -> web.StreamResponse:
        assert request.headers["Authorization"] == "Bearer test-provider-token"
        assert await request.read() == body
        if provider_status == 429:
            return web.json_response({"error": "quota"}, status=429, headers={"Retry-After": "9"})
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(first)
        await release.wait()
        await response.write(events("openai-chat"))
        await response.write_eof()
        return response

    application = web.Application()
    application.router.add_post("/provider", provider)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    backend = settings.stream_backends["openai-chat"]
    # Inject a loopback-only provider transport; deployed settings require HTTPS.
    settings.stream_backends["openai-chat"] = backend.model_copy(
        update={"endpoint": f"http://127.0.0.1:{port}"}
    )
    try:
        status, content_type, stream, headers = await relay.open(reservation_id, body)
        if provider_status == 429:
            assert status == 429 and content_type == "application/json"
            assert headers == {"Retry-After": "9"}
            assert json.loads(b"".join([chunk async for chunk in stream])) == {"error": "quota"}
            assert await engine.repository.get("settlements", reservation_id) is None
            assert sorted(engine.counters.counts.values()) == [100]
            return
        assert status == 200 and content_type == "text/event-stream"
        assert await asyncio.wait_for(anext(stream), 2) == first
        assert await engine.repository.get("settlements", reservation_id) is None
        release.set()
        assert b"".join([chunk async for chunk in stream]) == events("openai-chat")
        assert (await engine.repository.get("settlements", reservation_id))["data"][
            "cost_micro_usd"
        ] == 28
    finally:
        release.set()
        await runner.cleanup()


def test_reservation_fingerprint_pins_subscription_not_actor(request_body: Reserve) -> None:
    expected = digest(
        request_body.model_dump_json(
            exclude={
                "api_protocol": True,
                "payload_sha256": True,
                "principal_id": True,
                "usage": {"cache_write_input_tokens_5m", "cache_write_input_tokens_1h"},
            }
        )
    )
    assert reserve_fingerprint(request_body) == expected
    same_application = request_body.model_copy(update={"principal_id": "user-2"})
    other_application = request_body.model_copy(update={"subscription_id": "app-2"})
    assert reserve_fingerprint(same_application) == expected
    assert reserve_fingerprint(other_application) != expected


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic-messages"])
async def test_two_registered_streams_route_provider_names_but_charge_alias_prices(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    model_registry: dict[str, ModelDeployment],
    protocol: str,
) -> None:
    settings.model_registry = {
        key: entry for key, entry in model_registry.items() if entry.api_protocol == protocol
    }
    relay = StreamRelay(engine, Credential(), settings)
    destinations = set()
    for key, deployment in settings.model_registry.items():
        alias = key.partition(":")[2]
        premium = alias.endswith("premium")
        price = Price(
            id=alias,
            service="foundry",
            model=alias,
            version="v1",
            input_per_million="4" if premium else "2",
            output_per_million="8" if premium else "4",
            cached_input_per_million="1" if premium else "0.5",
            cache_write_5m_per_million="5" if premium else "2.5",
            cache_write_1h_per_million="8" if premium else "4",
            per_request="0",
        )
        await engine.repository.create("prices", alias, price.model_dump(mode="json"))
        body = json.dumps(
            {
                "model": deployment.model,
                "stream": True,
                **(
                    {"stream_options": {"include_usage": True}} if protocol == "openai-chat" else {}
                ),
            }
        ).encode()
        decision = await engine.reserve(
            request_body.model_copy(
                update={
                    "request_id": alias,
                    "model": alias,
                    "api_protocol": protocol,
                    "streaming": True,
                    "payload_sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        )
        assert decision.allowed
        request, backend = await relay.claim(decision.reservation_id, body)
        assert request.model == alias and request.model != backend.model
        assert backend == deployment
        destinations.add(str(backend.endpoint))
        wire = events(protocol)
        forwarded = b"".join(
            [
                chunk
                async for chunk in relay._stream(
                    request, decision.reservation_id, Response(wire), AsyncMock()
                )
            ]
        )
        assert forwarded == wire
        result = await engine.repository.get("settlements", decision.reservation_id)
        assert result["data"]["cost_micro_usd"] == (56 if premium else 28)
    assert len(destinations) == 2
    assert list(engine.counters.counts.values()) == [84]


async def test_registered_stream_does_not_fall_back_to_legacy_protocol_backend(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
    model_registry: dict[str, ModelDeployment],
) -> None:
    relay, reservation_id, body = await admitted(engine, settings, request_body)
    settings.model_registry = model_registry
    with pytest.raises(ValueError, match="Unknown model alias"):
        await relay.claim(reservation_id, body)
    assert await engine.repository.list("stream_dispatches") == []
