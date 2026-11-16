from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository


async def test_duplicate_admission_returns_the_first_context(settings: Settings) -> None:
    counters = MemoryCounters(settings)
    first = {"id": "one", "data": {"allowed": True}}

    assert await counters.admit("request", first) == (first, True)
    assert await counters.admit("request", {"id": "two"}) == (first, False)


async def test_duplicate_usage_returns_the_first_record_without_incrementing_again(
    settings: Settings,
) -> None:
    counters = MemoryCounters(settings)
    record = {"id": "one", "data": {"cost_micro_usd": 5, "counter_keys": ["k"]}}
    other = {"id": "two", "data": {"cost_micro_usd": 9, "counter_keys": ["k"]}}

    assert await counters.record("request", record) == (record, True)
    assert await counters.record("request", other) == (record, False)
    assert await counters.totals("2030-01", ["k"]) == {"k": 5}


async def test_repository_create_never_replaces_an_existing_record() -> None:
    repository = MemoryRepository()

    assert await repository.create_if_absent("usage", "r", {"id": "first"}) == (
        {"id": "first"},
        True,
    )
    assert await repository.create_if_absent("usage", "r", {"id": "second"}) == (
        {"id": "first"},
        False,
    )
