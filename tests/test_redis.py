import asyncio
import os
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Reserve, Settle, Usage
from apim_rate_limit_foundry.stores.contracts import Conflict, RecoveryRequired
from apim_rate_limit_foundry.stores.redis import RedisCounters

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_REDIS_URL"), reason="Set TEST_REDIS_URL for real Redis Lua tests"
)


@pytest_asyncio.fixture
async def redis_counters(settings: Settings):
    counters = RedisCounters.from_url(settings, os.environ["TEST_REDIS_URL"])
    counters.key = f"{{limiter-test-{uuid4().hex}}}:ledger"
    try:
        yield counters
    finally:
        await counters.client.delete(counters.key)
        await counters.close()


async def test_real_lua_concurrent_atomic_and_idempotent(
    redis_counters: RedisCounters,
    engine: Engine,
    request_body: Reserve,
) -> None:
    engine.counters = redis_counters
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body)
    await engine.recover()
    # Cold request did not receive admission. Its unknown liability remains conservative.
    retry = await engine.reserve(request_body)
    assert not retry.allowed
    await engine.repository.create(
        "policies",
        "request-cap",
        {
            "id": "request-cap",
            "name": "Requests",
            "service": "foundry",
            "limit": 1,
            "period": "hour",
            "metric": "requests",
        },
    )
    duplicate = request_body.model_copy(update={"request_id": "same"})
    results = await asyncio.gather(*(engine.reserve(duplicate) for _ in range(40)))
    assert all(r.allowed for r in results)
    assert len({r.reservation_id for r in results}) == 1
    counts_before = await redis_counters.client.hgetall(redis_counters.key)
    attempts = await asyncio.gather(
        *(
            engine.reserve(
                request_body.model_copy(
                    update={
                        "request_id": f"concurrent-{i}",
                    }
                )
            )
            for i in range(40)
        )
    )
    assert not any(r.allowed for r in attempts)
    counts_after = await redis_counters.client.hgetall(redis_counters.key)
    assert {k: v for k, v in counts_before.items() if k.startswith("c:")} == {
        k: v for k, v in counts_after.items() if k.startswith("c:")
    }
    with pytest.raises(Conflict):
        await engine.reserve(duplicate.model_copy(update={"operation": "other"}))
    actual = Settle(
        reservation_id=results[0].reservation_id,
        status="actual",
        usage=Usage(input_tokens=2, output_tokens=1),
    )
    await asyncio.gather(*(engine.settle(actual) for _ in range(30)))
    cost_key = (await engine.repository.get("intents", results[0].reservation_id))["data"][
        "debits"
    ][0]["key"]
    assert int(await redis_counters.client.hget(redis_counters.key, f"c:{cost_key}")) == 108
    with pytest.raises(Conflict):
        await engine.release(results[0].reservation_id)


async def test_real_lua_cache_loss_fails_closed_and_recovers(
    redis_counters: RedisCounters,
    engine: Engine,
    request_body: Reserve,
) -> None:
    engine.counters = redis_counters
    await engine.recover()
    first = await engine.reserve(request_body)
    await engine.settle(
        Settle(
            reservation_id=first.reservation_id,
            usage=Usage(input_tokens=1, output_tokens=1),
            status="actual",
        )
    )
    await redis_counters.client.delete(redis_counters.key)
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body)
    await engine.recover()
    assert (await engine.reserve(request_body)).allowed
    key = (await engine.repository.get("intents", first.reservation_id))["data"]["debits"][0]["key"]
    assert int(await redis_counters.client.hget(redis_counters.key, f"c:{key}")) == 6
    token = await redis_counters.begin_recovery()
    with pytest.raises(Conflict):
        await redis_counters.recover("wrong-token", [])
    await redis_counters.recover(token, [])


async def test_real_lua_concurrent_exhaustion_counts_each_policy_once(
    redis_counters: RedisCounters,
    engine: Engine,
    request_body: Reserve,
) -> None:
    engine.counters = redis_counters
    await engine.recover()
    await engine.repository.create(
        "policies",
        "request-cap",
        {
            "id": "request-cap",
            "name": "Requests",
            "service": "foundry",
            "limit": 4,
            "period": "hour",
            "metric": "requests",
        },
    )
    decisions = await asyncio.gather(
        *(
            engine.reserve(
                request_body.model_copy(
                    update={
                        "request_id": f"unique-{i}",
                    }
                )
            )
            for i in range(50)
        )
    )
    assert sum(d.allowed for d in decisions) == 3
    saved = await redis_counters.client.hgetall(redis_counters.key)
    assert sorted(int(v) for k, v in saved.items() if k.startswith("c:")) == [3, 300]


@pytest.mark.parametrize("minute_limit", [1, 100])
async def test_real_lua_denial_reset_tracks_all_blocking_policies(
    redis_counters: RedisCounters,
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
    frozen_accounting_time: datetime,
    minute_limit: int,
) -> None:
    engine.counters = redis_counters
    await engine.recover()
    monthly = policy.model_copy(update={"period": "month", "limit": 100})
    await engine.repository.mutate(
        "policies", monthly.id, monthly.model_dump(mode="json"), {"id": "month-change"}
    )
    await engine.repository.create(
        "policies",
        "minute",
        {
            "id": "minute",
            "name": "Requests",
            "service": "foundry",
            "limit": minute_limit,
            "period": "minute",
            "metric": "requests",
        },
    )
    assert (await engine.reserve(request_body)).allowed
    denied = await engine.reserve(request_body.model_copy(update={"request_id": "denied"}))
    assert denied.reset_at == "2030-12-01T00:00:00+00:00"
    assert denied.retry_after > 60
    assert denied.remaining_by_policy == {"policy-1": 0, "minute": minute_limit - 1}
    assert set(denied.denied_policy_ids) == (
        {"policy-1", "minute"} if minute_limit == 1 else {"policy-1"}
    )
