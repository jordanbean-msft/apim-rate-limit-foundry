from unittest.mock import AsyncMock

import pytest

from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.stores.contracts import Conflict


def check(request_id: str = "request-1") -> BudgetCheck:
    return BudgetCheck(
        request_id=request_id,
        tenant_id="tenant-1",
        principal_id="user-1",
        subscription_id="apim-subscription",
        model="model-1",
        api_protocol="openai-chat",
        streaming=False,
    )


def actual(request_id: str = "request-1") -> UsageRecordRequest:
    return UsageRecordRequest(
        request_id=request_id,
        status="actual",
        provider_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )


async def test_check_fails_closed_when_the_assigned_team_is_disabled(engine: Engine) -> None:
    team = await engine.repository.get("organizations", "team-1")
    assert team is not None
    await engine.repository.mutate(
        "organizations", "team-1", {**team, "enabled": False}, {"id": "a"}
    )

    with pytest.raises(ValueError, match="organization is unavailable"):
        await engine.check(check())

    assert await engine.counters.request("request-1") is None


async def test_losing_an_admission_race_replays_the_winning_decision(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    winner = await engine.check(check())
    saved = await engine.counters.request("request-1")
    monkeypatch.setattr(engine.counters, "request", AsyncMock(return_value=None))
    monkeypatch.setattr(engine.counters, "admit", AsyncMock(return_value=(saved, False)))

    loser = await engine.check(check())

    assert loser == winner


async def test_unmanaged_collections_are_listed_without_schema_validation(engine: Engine) -> None:
    await engine.repository.create("notes", "n1", {"id": "n1", "free": "form"})
    await engine.repository.create("notes", "n2", {"id": "n2", "_deleted": True})

    assert await engine.configuration("notes") == [{"id": "n1", "free": "form"}]


async def test_usage_requires_a_prior_admission(engine: Engine) -> None:
    with pytest.raises(Conflict, match="Budget check not found"):
        await engine.record_usage(actual("never-admitted"))


async def test_denied_requests_cannot_be_charged(engine: Engine) -> None:
    for budget_id in ("budget-user", "budget-team", "budget-department"):
        budget = await engine.repository.get("budgets", budget_id)
        assert budget is not None
        await engine.repository.mutate(
            "budgets", budget_id, {**budget, "limit_micro_usd": 0}, {"id": budget_id}
        )
    await engine.counters.invalidate_configuration()
    assert not (await engine.check(check()))["allowed"]

    with pytest.raises(Conflict, match="Denied requests cannot be charged"):
        await engine.record_usage(actual())


async def test_unknown_usage_rejects_fabricated_provider_counters(engine: Engine) -> None:
    await engine.check(check())

    with pytest.raises(ValueError, match="fabricated"):
        await engine.record_usage(
            UsageRecordRequest(
                request_id="request-1",
                status="usage_unknown",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )

    assert await engine.counters.usage("request-1") is None


async def test_a_usage_retry_that_loses_the_store_race_is_validated_and_replayed(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await engine.check(check())
    first = await engine.record_usage(actual())
    stored = await engine.counters.usage("request-1")
    monkeypatch.setattr(engine.counters, "usage", AsyncMock(return_value=None))
    monkeypatch.setattr(engine.counters, "record", AsyncMock(return_value=(stored, False)))

    raced = await engine.record_usage(actual())

    assert raced == {"event": first["event"], "replayed": True}
    with pytest.raises(Conflict, match="different provider usage"):
        await engine.record_usage(
            UsageRecordRequest(
                request_id="request-1",
                status="actual",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )


async def test_usage_retry_with_a_different_status_conflicts(engine: Engine) -> None:
    await engine.check(check())
    await engine.record_usage(UsageRecordRequest(request_id="request-1", status="usage_unknown"))

    with pytest.raises(Conflict, match="finalized differently"):
        await engine.record_usage(actual())
