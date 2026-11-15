import asyncio
import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.stores.redis import RedisCounters

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_REDIS_URL"),
    reason="Set TEST_REDIS_URL to an isolated disposable loopback Redis instance",
)


@pytest.fixture
async def cache(settings: Settings) -> AsyncIterator[RedisCounters]:
    url = os.environ["TEST_REDIS_URL"]
    if not url.startswith(("redis://127.0.0.1:", "redis://localhost:")):
        raise ValueError("Redis integration tests require a disposable loopback server")
    instance = RedisCounters.from_url(settings, url)
    yield instance
    await instance.close()


async def test_real_redis_usage_is_atomic_and_idempotent_across_concurrent_writers(
    cache: RedisCounters,
) -> None:
    request_id = uuid4().hex
    keys = [f"{request_id}-{index}" for index in range(6)]
    record = {
        "id": request_id,
        "data": {"month": "2030-01", "cost_micro_usd": 123, "counter_keys": keys},
    }

    results = await asyncio.gather(*(cache.record(request_id, record) for _ in range(30)))

    assert sum(created for _, created in results) == 1
    assert all(saved == record for saved, _ in results)
    assert await cache.totals("2030-01", keys) == dict.fromkeys(keys, 123)
    assert await cache.totals("2030-02", keys) == dict.fromkeys(keys, 0)
    changed = {"id": request_id, "data": {**record["data"], "cost_micro_usd": 999}}
    assert await cache.record(request_id, changed) == (record, False)
    assert await cache.totals("2030-01", keys) == dict.fromkeys(keys, 123)


async def test_real_redis_admission_replays_context_and_unknown_usage_does_not_increment(
    cache: RedisCounters,
) -> None:
    request_id = uuid4().hex
    context = {"id": request_id, "tenant_id": "tenant", "data": {"allowed": True}}
    admissions = await asyncio.gather(*(cache.admit(request_id, context) for _ in range(20)))
    assert sum(created for _, created in admissions) == 1
    assert await cache.request(request_id) == context
    client = await cache.connection()
    ttl = await client.ttl(f"{{limiter}}:request:v3:{request_id}")
    assert cache.settings.request_cache_seconds - 1 <= ttl <= cache.settings.request_cache_seconds
    unknown = {
        "id": request_id,
        "data": {"month": "2030-01", "cost_micro_usd": None, "counter_keys": [request_id]},
    }
    assert await cache.record(request_id, unknown) == (unknown, True)
    assert await cache.usage(request_id) == unknown
    assert await cache.totals("2030-01", [request_id]) == {request_id: 0}


async def test_real_redis_configuration_is_invalidated_and_expiring(
    cache: RedisCounters,
) -> None:
    snapshot = {"budgets": [{"id": uuid4().hex, "limit_micro_usd": 123}]}
    await cache.cache_configuration(snapshot)
    assert await cache.configuration() == snapshot
    client = await cache.connection()
    ttl = await client.ttl(cache.configuration_key)
    assert (
        cache.settings.configuration_cache_seconds - 1
        <= ttl
        <= cache.settings.configuration_cache_seconds
    )
    await cache.invalidate_configuration()
    assert await cache.configuration() is None


async def test_real_redis_engine_enforces_live_budgets_while_table_is_blocked(
    cache: RedisCounters, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = uuid4().hex
    snapshot = {
        collection: await engine.configuration(collection)
        for collection in ("assignments", "organizations", "budgets", "prices")
    }
    for records in snapshot.values():
        for record in records:
            if "tenant_id" in record:
                record["tenant_id"] = tenant
    await cache.cache_configuration(snapshot)
    engine.counters = cache
    release = asyncio.Event()
    started = asyncio.Event()

    async def blocked_write(*args):
        started.set()
        await release.wait()
        return args[-1]

    no_reads = AsyncMock(side_effect=AssertionError("Table read on the warm Redis path"))
    monkeypatch.setattr(engine.repository, "list", no_reads)
    monkeypatch.setattr(engine.repository, "get", no_reads)
    monkeypatch.setattr(engine.repository, "create", blocked_write)
    request = BudgetCheck(
        request_id=uuid4().hex,
        tenant_id=tenant,
        principal_id="user-1",
        subscription_id="apim-app",
        model="model-1",
        api_protocol="openai-chat",
        streaming=False,
    )
    try:
        async with asyncio.timeout(1):
            assert (await engine.check(request))["allowed"]
            await started.wait()
            accepted = await engine.record_usage(
                UsageRecordRequest(
                    request_id=request.request_id,
                    status="actual",
                    provider_usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                )
            )
            assert accepted["event"]["cost_micro_usd"] == 100
            denied = await engine.check(request.model_copy(update={"request_id": uuid4().hex}))
            assert not denied["allowed"]
            assert len(denied["denied_budget_ids"]) == 3
            assert not release.is_set()
        no_reads.assert_not_awaited()
    finally:
        release.set()
        await engine.background.flush()
