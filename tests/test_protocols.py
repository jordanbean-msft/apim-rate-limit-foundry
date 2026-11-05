import asyncio
import json
import os
from uuid import uuid4

import httpx
import pytest

from apim_rate_limit_foundry.accounting import cost, digest
from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.normalization.anthropic import normalize_anthropic
from apim_rate_limit_foundry.normalization.openai import normalize_openai
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.stores.memory import MemoryCounters


@pytest.fixture
def anthropic_usage() -> dict:
    return {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 30,
        "cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 10},
    }


@pytest.fixture
def anthropic_price() -> Price:
    return Price(
        id="claude",
        service="foundry",
        model="claude",
        version="1",
        per_request="0",
        input_per_million="3",
        output_per_million="15",
        cached_input_per_million="0.30",
        cache_write_5m_per_million="3.75",
        cache_write_1h_per_million="6",
    )


@pytest.fixture
async def protocol_engine(
    engine: Engine, policy: Policy, price: Price, anthropic_price: Price
) -> Engine:
    await engine.repository.mutate(
        "policies",
        policy.id,
        {
            **policy.model_dump(mode="json"),
            "limit": 5000,
        },
        {"id": "larger-budget"},
    )
    await engine.repository.mutate(
        "prices",
        price.id,
        {
            **price.model_dump(mode="json"),
            "output_per_million": "8",
            "cached_input_per_million": "0.2",
        },
        {"id": "openai-price"},
    )
    await engine.repository.create(
        "prices", anthropic_price.id, anthropic_price.model_dump(mode="json")
    )
    await engine.repository.create(
        "policies",
        "tokens",
        {
            "id": "tokens",
            "name": "All tokens",
            "service": "foundry",
            "limit": 5000,
            "period": "day",
            "metric": "tokens",
        },
    )
    return engine


@pytest.fixture
def anthropic_request(request_body: Reserve) -> Reserve:
    return request_body.model_copy(
        update={
            "api_protocol": "anthropic-messages",
            "model": "claude",
            "usage": Usage(input_tokens=200, output_tokens=20),
        }
    )


@pytest.mark.parametrize(
    ("protocol", "raw"),
    [
        (
            "openai-chat",
            {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 50},
            },
        ),
        (
            "openai-responses",
            {
                "input_tokens": 100,
                "output_tokens": 10,
                "input_tokens_details": {"cached_tokens": 50},
            },
        ),
    ],
)
async def test_openai_protocols_normalize_and_canonicalize_retries(
    protocol_engine: Engine,
    request_body: Reserve,
    protocol: str,
    raw: dict,
) -> None:
    request = request_body.model_copy(
        update={
            "api_protocol": protocol,
            "usage": Usage(input_tokens=120, output_tokens=20),
        }
    )
    decision = await protocol_engine.reserve(request)
    settlement = Settle(reservation_id=decision.reservation_id, status="actual", provider_usage=raw)
    results = await asyncio.gather(*(protocol_engine.settle(settlement) for _ in range(10)))
    assert results[0]["data"]["cost_micro_usd"] == 190
    assert not results[0]["data"]["estimated"]
    reordered = {**dict(reversed(list(raw.items()))), "total_tokens": 110}
    await protocol_engine.settle(settlement.model_copy(update={"provider_usage": reordered}))
    output_field = "completion_tokens" if protocol == "openai-chat" else "output_tokens"
    with pytest.raises(Conflict):
        await protocol_engine.settle(
            settlement.model_copy(
                update={
                    "provider_usage": {**raw, output_field: 11},
                }
            )
        )
    assert sorted(protocol_engine.counters.counts.values()) == [110, 190]


async def test_anthropic_total_input_cost_and_provenance(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    anthropic_usage: dict,
) -> None:
    decision = await protocol_engine.reserve(anthropic_request)
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]
    original = await protocol_engine.repository.get("intents", decision.reservation_id)
    changed_price = {**original["data"]["price"], "cache_write_1h_per_million": "99"}
    await protocol_engine.repository.mutate(
        "prices", "claude", changed_price, {"id": "changed-price"}
    )
    settlement = Settle(
        reservation_id=decision.reservation_id, status="actual", provider_usage=anthropic_usage
    )
    actual = await protocol_engine.settle(settlement)
    assert actual["data"]["cost_micro_usd"] == 600
    assert actual["data"]["usage"]["input_tokens"] == 180
    assert actual["data"]["usage"]["cached_input_tokens"] == 50
    assert actual["data"]["usage"]["cache_write_input_tokens_5m"] == 20
    assert actual["data"]["usage"]["cache_write_input_tokens_1h"] == 10
    assert actual["data"]["cache_write_input_reported"]
    equivalent = {**dict(reversed(list(anthropic_usage.items()))), "service_tier": "standard"}
    equivalent["cache_creation"] = dict(reversed(list(anthropic_usage["cache_creation"].items())))
    await protocol_engine.settle(settlement.model_copy(update={"provider_usage": equivalent}))
    protocol_engine.counters = MemoryCounters(ready=False)
    await protocol_engine.recover()
    assert sorted(protocol_engine.counters.counts.values()) == [190, 600]
    await protocol_engine.settle(settlement)
    report = await protocol_engine.report("usage", "tenant-1", "user-1", False)
    assert report[0]["data"]["api_protocol"] == "anthropic-messages"
    assert report[0]["data"]["cost_micro_usd"] == 600
    summary = (
        await UsageSummaryService(protocol_engine.repository).summarize(
            "day",
            "tenant-1",
            "user-1",
            False,
        )
    )[0]
    assert summary.api_protocol == "anthropic-messages"
    assert summary.cost_micro_usd == 600 and summary.input_tokens == 180
    assert (summary.cache_write_input_tokens_5m, summary.cache_write_input_tokens_1h) == (20, 10)


@pytest.mark.parametrize(
    "missing", ["cache_read_input_tokens", "cache_creation_input_tokens", "cache_creation"]
)
async def test_incomplete_anthropic_usage_never_refunds_or_finalizes(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    anthropic_usage: dict,
    missing: str,
) -> None:
    decision = await protocol_engine.reserve(anthropic_request)
    incomplete = {key: value for key, value in anthropic_usage.items() if key != missing}
    pending = await protocol_engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            provider_usage=incomplete,
        )
    )
    assert pending["data"]["estimated"] and pending["data"]["status"] == "conservative"
    assert pending["data"]["reason"] == "incomplete_provider_usage"
    assert not await protocol_engine.repository.list("settlements")
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]
    protocol_engine.counters = MemoryCounters(ready=False)
    await protocol_engine.recover()
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]
    await protocol_engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            provider_usage=anthropic_usage,
        )
    )
    assert sorted(protocol_engine.counters.counts.values()) == [190, 600]


@pytest.mark.parametrize("bad", [True, -1, 0.5, "1", 9_000_000_000_001, None])
async def test_invalid_provider_counters_retain_conservative_debits(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    anthropic_usage: dict,
    bad: object,
) -> None:
    decision = await protocol_engine.reserve(anthropic_request)
    with pytest.raises(ValueError):
        await protocol_engine.settle(
            Settle(
                reservation_id=decision.reservation_id,
                status="actual",
                provider_usage={**anthropic_usage, "cache_read_input_tokens": bad},
            )
        )
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]
    assert not await protocol_engine.repository.list("settlements")


async def test_cache_ttl_mismatch_and_total_bounds_never_refund(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    anthropic_usage: dict,
) -> None:
    decision = await protocol_engine.reserve(anthropic_request)
    for changed in (
        {"cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 9}},
        {"input_tokens": 200},
    ):
        with pytest.raises(ValueError):
            await protocol_engine.settle(
                Settle(
                    reservation_id=decision.reservation_id,
                    status="actual",
                    provider_usage={**anthropic_usage, **changed},
                )
            )
    with pytest.raises(ValueError, match="subset"):
        Usage(input_tokens=10, cached_input_tokens=5, cache_write_input_tokens_5m=6)
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]


@pytest.mark.parametrize("field", ["cache_write_5m_per_million", "cache_write_1h_per_million"])
async def test_anthropic_unknown_potential_write_prices_deny_admission(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    anthropic_price: Price,
    field: str,
) -> None:
    unknown = {**anthropic_price.model_dump(mode="json"), field: None}
    await protocol_engine.repository.mutate("prices", anthropic_price.id, unknown, {"id": field})
    with pytest.raises(ValueError, match="Unknown"):
        await protocol_engine.reserve(anthropic_request)
    assert not protocol_engine.counters.counts


async def test_streaming_and_missing_openai_counters_remain_conservative(
    protocol_engine: Engine,
    anthropic_request: Reserve,
    request_body: Reserve,
) -> None:
    stream = await protocol_engine.reserve(anthropic_request.model_copy(update={"streaming": True}))
    await protocol_engine.release(stream.reservation_id)
    assert sorted(protocol_engine.counters.counts.values()) == [220, 1500]
    request = request_body.model_copy(update={"request_id": "chat"})
    chat = await protocol_engine.reserve(request)
    snapshot = dict(protocol_engine.counters.counts)
    pending = await protocol_engine.settle(
        Settle(
            reservation_id=chat.reservation_id,
            status="actual",
            provider_usage={"prompt_tokens": 0},
        )
    )
    assert pending["data"]["estimated"] and protocol_engine.counters.counts == snapshot
    explicit_zero = await protocol_engine.settle(
        Settle(
            reservation_id=chat.reservation_id,
            status="actual",
            provider_usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        )
    )
    assert explicit_zero["data"]["cost_micro_usd"] == 0
    assert not explicit_zero["data"]["estimated"]


def test_anthropic_zero_creation_requires_no_ttl_object(
    anthropic_usage: dict, anthropic_price: Price
) -> None:
    raw = {**anthropic_usage, "cache_creation_input_tokens": 0}
    raw.pop("cache_creation")
    usage = normalize_anthropic(raw)
    assert usage.input_tokens == 150
    assert cost(anthropic_price, usage, False, "anthropic-messages") == 465


def test_openai_missing_cache_is_not_explicit_zero() -> None:
    unknown = normalize_openai({"input_tokens": 10, "output_tokens": 0}, "openai-responses")
    known_zero = normalize_openai(
        {
            "input_tokens": 10,
            "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
        },
        "openai-responses",
    )
    assert "cached_input_tokens" not in unknown.model_fields_set
    assert "cached_input_tokens" in known_zero.model_fields_set
    with pytest.raises(ValueError, match="total_tokens"):
        normalize_openai(
            {"input_tokens": 10, "output_tokens": 0, "total_tokens": 11}, "openai-responses"
        )


async def test_protocol_and_usage_source_are_not_settlement_overrides(
    protocol_engine: Engine,
    settings: Settings,
    request_body: Reserve,
    anthropic_usage: dict,
) -> None:
    headers = {
        "X-Local-Tenant-Id": "tenant-1",
        "X-Local-Principal-Id": "gateway",
        "X-Local-Roles": "RateLimit.Gateway",
    }
    decision = await protocol_engine.reserve(request_body)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, protocol_engine)),
        base_url="http://test",
    ) as client:
        body = {
            "reservation_id": decision.reservation_id,
            "status": "actual",
            "provider_usage": anthropic_usage,
        }
        assert (
            await client.post(
                "/api/decisions/settle",
                json={
                    **body,
                    "api_protocol": "anthropic-messages",
                },
                headers=headers,
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/decisions/settle",
                json={
                    **body,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
                headers=headers,
            )
        ).status_code == 422
        response = await client.post("/api/decisions/settle", json=body, headers=headers)
        assert response.json()["data"]["reason"] == "incomplete_provider_usage"
    assert not await protocol_engine.repository.list("settlements")


async def test_legacy_price_reservation_and_settlement_fingerprints_survive(
    engine: Engine,
    request_body: Reserve,
) -> None:
    first = await engine.reserve(request_body)
    intent = engine.repository.records["intents", first.reservation_id]
    for data in (intent["data"], engine.repository.records["usage", first.reservation_id]["data"]):
        data["request"].pop("api_protocol", None)
        for field in ("cache_write_input_tokens_5m", "cache_write_input_tokens_1h"):
            data["request"]["usage"].pop(field, None)
        data["price"].pop("cache_write_5m_per_million", None)
        data["price"].pop("cache_write_1h_per_million", None)
    legacy_json = json.dumps(intent["data"]["request"], separators=(",", ":"))
    assert intent["data"]["fingerprint"] == digest(legacy_json)
    actual = Settle(
        reservation_id=first.reservation_id,
        status="actual",
        usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=0),
    )
    settled = await engine.settle(actual)
    legacy_actual = actual.model_dump(mode="json", exclude={"provider_usage"})
    for field in ("cache_write_input_tokens_5m", "cache_write_input_tokens_1h"):
        legacy_actual["usage"].pop(field)
    expected = digest(json.dumps(legacy_actual, separators=(",", ":")), "True")
    assert settled["data"]["fingerprint"] == expected
    engine.counters = MemoryCounters(ready=False)
    await engine.recover()
    assert (
        await engine.reserve(request_body.model_copy(update={"api_protocol": "openai-chat"}))
    ).allowed
    await engine.settle(actual)
    assert list(engine.counters.counts.values()) == [24]


@pytest.mark.skipif(
    not os.environ.get("TEST_REDIS_URL") or not os.environ.get("TEST_TABLE_CONNECTION_STRING"),
    reason="Set Redis and Azurite test endpoints for protocol persistence integration",
)
async def test_real_redis_azurite_protocol_settlement_and_recovery(
    anthropic_request: Reserve,
    anthropic_usage: dict,
    anthropic_price: Price,
    policy: Policy,
) -> None:
    settings = Settings(
        _env_file=None,
        local_store_enabled=True,
        local_redis_url=os.environ["TEST_REDIS_URL"],
        local_table_connection_string=os.environ["TEST_TABLE_CONNECTION_STRING"],
        table_name=f"Protocol{uuid4().hex}",
    )
    runtime = Runtime(settings)
    counters, repository = runtime.engine.counters, runtime.engine.repository
    counters.key = f"{{protocol-{uuid4().hex}}}:ledger"
    client = await counters.connection()
    try:
        await repository.client.create_table()
        await repository.create(
            "prices", anthropic_price.id, anthropic_price.model_dump(mode="json")
        )
        await repository.create(
            "policies",
            policy.id,
            {
                **policy.model_dump(mode="json"),
                "limit": 5000,
            },
        )
        await repository.create(
            "policies",
            "tokens",
            {
                "id": "tokens",
                "name": "Tokens",
                "service": "foundry",
                "limit": 5000,
                "metric": "tokens",
                "period": "day",
            },
        )
        await runtime.engine.recover()
        decision = await runtime.engine.reserve(anthropic_request)
        incomplete = {
            key: value for key, value in anthropic_usage.items() if key != "cache_creation"
        }
        await runtime.engine.settle(
            Settle(
                reservation_id=decision.reservation_id,
                status="actual",
                provider_usage=incomplete,
            )
        )
        await client.delete(counters.key)
        await runtime.engine.recover()
        cached = await client.hgetall(counters.key)
        assert sorted(int(value) for key, value in cached.items() if key.startswith("c:")) == [
            220,
            1500,
        ]
        settlement = Settle(
            reservation_id=decision.reservation_id, status="actual", provider_usage=anthropic_usage
        )
        await runtime.engine.settle(settlement)
        await client.delete(counters.key)
        await runtime.engine.recover()
        assert (await runtime.engine.reserve(anthropic_request)).allowed
        await runtime.engine.settle(
            settlement.model_copy(
                update={
                    "provider_usage": dict(reversed(list(anthropic_usage.items()))),
                }
            )
        )
        cached = await client.hgetall(counters.key)
        assert sorted(int(value) for key, value in cached.items() if key.startswith("c:")) == [
            190,
            600,
        ]
        stored = (await repository.list("settlements"))[0]
        assert stored["data"]["api_protocol"] == "anthropic-messages"
        assert stored["data"]["usage"]["cache_write_input_tokens_1h"] == 10
    finally:
        await client.delete(counters.key)
        await repository.client.delete_table()
        await runtime.close()
