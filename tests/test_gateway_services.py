from unittest.mock import AsyncMock

import pytest

from apim_rate_limit_foundry.engine import GatewayServices
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


async def test_check_fails_closed_when_the_assigned_team_is_disabled(
    gateway: GatewayServices,
) -> None:
    team = await gateway.repository.get("organizations", "team-1")
    assert team is not None
    await gateway.repository.mutate(
        "organizations", "team-1", {**team, "enabled": False}, {"id": "a"}
    )

    with pytest.raises(ValueError, match="organization is unavailable"):
        await gateway.admission.check(check())

    assert await gateway.counters.request("request-1") is None


async def test_losing_an_admission_race_replays_the_winning_decision(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    winner = await gateway.admission.check(check())
    saved = await gateway.counters.request("request-1")
    monkeypatch.setattr(gateway.counters, "request", AsyncMock(return_value=None))
    monkeypatch.setattr(gateway.counters, "admit", AsyncMock(return_value=(saved, False)))

    loser = await gateway.admission.check(check())

    assert loser == winner


async def test_unmanaged_collections_are_listed_without_schema_validation(
    gateway: GatewayServices,
) -> None:
    await gateway.repository.create("notes", "n1", {"id": "n1", "free": "form"})
    await gateway.repository.create("notes", "n2", {"id": "n2", "_deleted": True})

    assert await gateway.configuration.list("notes") == [{"id": "n1", "free": "form"}]


async def test_usage_requires_a_prior_admission(gateway: GatewayServices) -> None:
    with pytest.raises(Conflict, match="Budget check not found"):
        await gateway.usage.record(actual("never-admitted"))


async def test_denied_requests_cannot_be_charged(gateway: GatewayServices) -> None:
    for budget_id in ("budget-user", "budget-team", "budget-department"):
        budget = await gateway.repository.get("budgets", budget_id)
        assert budget is not None
        await gateway.repository.mutate(
            "budgets", budget_id, {**budget, "limit_micro_usd": 0}, {"id": budget_id}
        )
    await gateway.counters.invalidate_configuration()
    assert not (await gateway.admission.check(check()))["allowed"]

    with pytest.raises(Conflict, match="Denied requests cannot be charged"):
        await gateway.usage.record(actual())


async def test_unknown_usage_rejects_fabricated_provider_counters(gateway: GatewayServices) -> None:
    await gateway.admission.check(check())

    with pytest.raises(ValueError, match="fabricated"):
        await gateway.usage.record(
            UsageRecordRequest(
                request_id="request-1",
                status="usage_unknown",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )

    assert await gateway.counters.usage("request-1") is None


async def test_a_usage_retry_that_loses_the_store_race_is_validated_and_replayed(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.check(check())
    first = await gateway.usage.record(actual())
    stored = await gateway.counters.usage("request-1")
    monkeypatch.setattr(gateway.counters, "usage", AsyncMock(return_value=None))
    monkeypatch.setattr(gateway.counters, "record", AsyncMock(return_value=(stored, False)))

    raced = await gateway.usage.record(actual())

    assert raced == {"event": first["event"], "replayed": True}
    with pytest.raises(Conflict, match="different provider usage"):
        await gateway.usage.record(
            UsageRecordRequest(
                request_id="request-1",
                status="actual",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )


async def test_usage_retry_with_a_different_status_conflicts(gateway: GatewayServices) -> None:
    await gateway.admission.check(check())
    await gateway.usage.record(UsageRecordRequest(request_id="request-1", status="usage_unknown"))

    with pytest.raises(Conflict, match="finalized differently"):
        await gateway.usage.record(actual())


async def test_usage_is_accepted_when_budget_balances_cannot_be_read(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.check(check())
    monkeypatch.setattr(gateway.counters, "totals", AsyncMock(side_effect=OSError("redis down")))

    result = await gateway.usage.record(actual())

    assert result["replayed"] is False
    assert await gateway.counters.usage("request-1") is not None


async def test_usage_for_a_context_saved_before_budgets_were_pinned_reports_no_balances(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.check(check())
    saved = await gateway.counters.request("request-1")
    assert saved is not None
    del saved["data"]["budgets"]
    monkeypatch.setattr(gateway.counters, "request", AsyncMock(return_value=saved))
    totals = AsyncMock()
    monkeypatch.setattr(gateway.counters, "totals", totals)

    await gateway.usage.record(actual())

    totals.assert_not_awaited()


async def test_budget_status_and_model_access_use_the_cached_snapshot_not_table(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.has_assignment("tenant-1", "user-1")
    forbidden = AsyncMock(side_effect=AssertionError("Table must not be read"))
    monkeypatch.setattr(gateway.repository, "list", forbidden)
    monkeypatch.setattr(gateway.repository, "get", forbidden)

    admin_rows = await gateway.reports.budget_status("tenant-1", "admin", admin=True)
    reader_rows = await gateway.reports.budget_status("tenant-1", "user-1")

    assert admin_rows and reader_rows
    assert await gateway.admission.has_assignment("tenant-1", "user-1")
    forbidden.assert_not_awaited()
