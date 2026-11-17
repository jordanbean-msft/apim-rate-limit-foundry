import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import NoScriptError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.scripts import RECORD_USAGE, RECORD_USAGE_SHA
from apim_rate_limit_foundry.telemetry.dependency import dependency_span


class FakeRedis:
    """Minimal in-memory stand-in for the Redis commands the counters issue."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.evalsha = AsyncMock()
        self.script_load = AsyncMock()
        self.aclose = AsyncMock()

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiry[key] = ex
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def hmget(self, key: str, fields: list[str]) -> list[str | None]:
        return [self.hashes.get(key, {}).get(field) for field in fields]


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def counters(settings: Settings, redis: FakeRedis) -> RedisCounters:
    return RedisCounters(settings, None, redis)  # type: ignore[arg-type]


def test_url_clients_are_limited_to_explicit_local_store_mode() -> None:
    cloud = Settings(_env_file=None)

    with pytest.raises(ValueError, match="explicit local store mode"):
        RedisCounters.from_url(cloud, "redis://127.0.0.1:6379")


async def test_url_clients_are_built_in_local_mode(settings: Settings) -> None:
    store = RedisCounters.from_url(settings, "redis://127.0.0.1:6379")

    assert store.static_client
    await store.close()


async def test_configuration_snapshots_round_trip_expire_and_invalidate(
    counters: RedisCounters, redis: FakeRedis
) -> None:
    assert await counters.configuration() is None

    await counters.cache_configuration({"budgets": [{"id": "b"}]})

    assert await counters.configuration() == {"budgets": [{"id": "b"}]}
    assert redis.expiry[counters.configuration_key] == counters.settings.configuration_cache_seconds
    await counters.invalidate_configuration()
    assert await counters.configuration() is None


async def test_admission_is_first_writer_wins_and_duplicates_read_the_winner(
    counters: RedisCounters, redis: FakeRedis
) -> None:
    winner = {"id": "one", "data": {"allowed": True}}

    created = await counters.admit("request", winner)
    duplicate = await counters.admit("request", {"id": "two"})

    assert created == (winner, True)
    assert duplicate == (winner, False)
    assert await counters.request("request") == winner
    assert redis.expiry["{limiter}:request:v3:request"] == counters.settings.request_cache_seconds


async def test_a_duplicate_whose_winner_expired_fails_instead_of_admitting(
    counters: RedisCounters, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis.values["{limiter}:request:v3:request"] = "{}"
    monkeypatch.setattr(counters, "request", AsyncMock(return_value=None))

    with pytest.raises(OSError, match="expired during replay"):
        await counters.admit("request", {"id": "late"})


async def test_usage_reads_return_none_until_finalized(
    counters: RedisCounters, redis: FakeRedis
) -> None:
    assert await counters.usage("request") is None

    redis.values["{limiter}:usage:v3:request"] = json.dumps({"id": "done"})

    assert await counters.usage("request") == {"id": "done"}


async def test_record_submits_hierarchy_keys_only_for_known_costs(
    counters: RedisCounters, redis: FakeRedis
) -> None:
    redis.evalsha.side_effect = [
        [json.dumps({"id": "known"}), 1],
        [json.dumps({"id": "unknown"}), 0],
    ]
    known = {
        "id": "known",
        "data": {"month": "2030-01", "cost_micro_usd": 7, "counter_keys": ["k"]},
    }
    unknown = {
        "id": "u",
        "data": {"month": "2030-01", "cost_micro_usd": None, "counter_keys": ["k"]},
    }

    assert await counters.record("one", known) == ({"id": "known"}, True)
    assert await counters.record("two", unknown) == ({"id": "unknown"}, False)

    known_call, unknown_call = (call.args for call in redis.evalsha.await_args_list)
    assert known_call[2:4] == ("{limiter}:usage:v3:one", "{limiter}:spend:v3:2030-01")
    assert (known_call[7], json.loads(known_call[8])) == ("7", ["k"])
    assert (unknown_call[7], json.loads(unknown_call[8])) == ("0", [])


async def test_record_loads_the_script_once_when_the_server_lacks_it(
    counters: RedisCounters, redis: FakeRedis
) -> None:
    redis.evalsha.side_effect = [NoScriptError("NOSCRIPT"), [json.dumps({"id": "known"}), 1]]
    record = {"id": "known", "data": {"month": "2030-01", "cost_micro_usd": 7, "counter_keys": []}}

    assert await counters.record("one", record) == ({"id": "known"}, True)

    redis.script_load.assert_awaited_once_with(RECORD_USAGE)
    assert redis.evalsha.await_count == 2
    assert redis.evalsha.await_args_list[0].args[0] == RECORD_USAGE_SHA


async def test_record_script_sha_matches_its_body() -> None:
    assert hashlib.sha1(RECORD_USAGE.encode()).hexdigest() == RECORD_USAGE_SHA


async def test_totals_treat_missing_spend_as_zero_and_skip_empty_reads(
    counters: RedisCounters, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis.hashes["{limiter}:spend:v3:2030-01"] = {"a": "12"}
    connection = AsyncMock(wraps=counters.connection)
    monkeypatch.setattr(counters, "connection", connection)

    assert await counters.totals("2030-01", []) == {}
    connection.assert_not_awaited()
    assert await counters.totals("2030-01", ["a", "b"]) == {"a": 12, "b": 0}


async def test_close_releases_the_client(counters: RedisCounters, redis: FakeRedis) -> None:
    await counters.close()

    redis.aclose.assert_awaited_once()


async def test_configuration_cache_writes_and_invalidations_are_dependency_spans(
    counters: RedisCounters, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations: list[str] = []
    real = dependency_span

    def spy(dependency: str, operation: str):
        operations.append(f"{dependency}.{operation}")
        return real(dependency, operation)

    monkeypatch.setattr("apim_rate_limit_foundry.telemetry.dependency.dependency_span", spy)

    await counters.cache_configuration({"budgets": []})
    await counters.invalidate_configuration()

    assert operations == ["redis.cache_configuration", "redis.invalidate_configuration"]
