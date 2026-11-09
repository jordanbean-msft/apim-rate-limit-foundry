import asyncio
from datetime import UTC, datetime

import pytest

from apim_rate_limit_foundry.accounting import utc_month
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.price import Price
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.stores.memory import MemoryCounters


def check(request_id: str = "request-1", **changes: object) -> BudgetCheck:
    payload: dict[str, object] = {
        "request_id": request_id,
        "tenant_id": "tenant-1",
        "principal_id": "user-1",
        "subscription_id": "apim-subscription",
        "model": "model-1",
        "api_protocol": "openai-chat",
        "streaming": False,
    }
    payload.update(changes)
    return BudgetCheck.model_validate(payload)


def actual(request_id: str = "request-1") -> UsageRecordRequest:
    return UsageRecordRequest(
        request_id=request_id,
        status="actual",
        provider_usage={
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    )


async def test_hierarchy_budgets_are_snapshotted_and_all_exhausted_levels_deny(
    engine: Engine,
) -> None:
    admitted = await engine.check(check())
    assert admitted["allowed"] is True
    assert admitted["denied_budget_ids"] == []

    recorded = await engine.record_usage(actual())
    assert recorded["replayed"] is False
    assert recorded["event"]["cost_micro_usd"] == 100
    assert recorded["event"]["business_unit"] == "BU-ENG"
    assert recorded["event"]["cost_center"] == "CC-100"

    denied = await engine.check(check("request-2"))
    assert denied["allowed"] is False
    assert set(denied["denied_budget_ids"]) == {
        "budget-user",
        "budget-team",
        "budget-department",
    }


async def test_check_is_idempotent_conflict_protected_and_completed_ids_rejected(
    engine: Engine,
) -> None:
    first = await engine.check(check())
    replay = await engine.check(check())
    assert first == replay
    with pytest.raises(Conflict, match="different request"):
        await engine.check(check("request-1", model="other"))

    await engine.record_usage(actual())
    with pytest.raises(Conflict, match="Completed"):
        await engine.check(check())


async def test_post_request_soft_cap_allows_in_flight_requests_to_overshoot(
    engine: Engine,
) -> None:
    checks = await asyncio.gather(
        engine.check(check("inflight-1")), engine.check(check("inflight-2"))
    )
    assert all(result["allowed"] for result in checks)
    await engine.record_usage(actual("inflight-1"))
    await engine.record_usage(actual("inflight-2"))
    next_request = await engine.check(check("next"))
    assert next_request["allowed"] is False


@pytest.mark.parametrize("subject_type", ["user", "team", "department", None])
async def test_each_configured_zero_budget_blocks_but_unconfigured_levels_do_not(
    engine: Engine, subject_type: str | None
) -> None:
    for kind in ("user", "team", "department"):
        budget_id = f"budget-{kind}"
        budget = await engine.repository.get("budgets", budget_id)
        assert budget is not None
        budget.update(enabled=kind == subject_type, limit_micro_usd=0)
        await engine.repository.mutate("budgets", budget_id, budget, {"id": f"audit-{kind}"})

    decision = await engine.check(check())

    assert decision["allowed"] is (subject_type is None)
    assert decision["denied_budget_ids"] == ([f"budget-{subject_type}"] if subject_type else [])


async def test_month_rollover_resets_budgets_and_preserves_inflight_accounting_month(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apim_rate_limit_foundry.engine.utc_month",
        lambda: utc_month(datetime(2030, 12, 31, 23, 59, tzinfo=UTC)),
    )
    await engine.check(check("completed-december"))
    await engine.check(check("inflight-december"))
    await engine.record_usage(actual("completed-december"))
    assert not (await engine.check(check("denied-december")))["allowed"]
    monkeypatch.setattr(
        "apim_rate_limit_foundry.engine.utc_month",
        lambda: utc_month(datetime(2031, 1, 1, tzinfo=UTC)),
    )

    late_record = await engine.record_usage(actual("inflight-december"))
    january = await engine.check(check("fresh-january"))

    assert late_record["event"]["month"] == "2030-12"
    assert january["allowed"]
    assert (
        sum(row["cost_micro_usd"] for row in await engine.chargeback("tenant-1", "2030-12", None))
        == 200
    )
    assert await engine.chargeback("tenant-1", "2031-01", None) == []


async def test_wildcard_budget_accumulates_spend_across_models(engine: Engine) -> None:
    for kind in ("user", "team", "department"):
        budget_id = f"budget-{kind}"
        budget = await engine.repository.get("budgets", budget_id)
        assert budget is not None
        budget["limit_micro_usd"] = 200
        await engine.repository.mutate("budgets", budget_id, budget, {"id": f"audit-{kind}"})
    second_price = Price(
        id="price-2",
        model="model-2",
        version="v1",
        input_per_million="2",
        cached_input_per_million="0.5",
        output_per_million="4",
    )
    await engine.repository.create("prices", second_price.id, second_price.model_dump(mode="json"))
    await engine.check(check())
    await engine.record_usage(actual())
    second = check("request-2", model="model-2")
    assert (await engine.check(second))["allowed"]
    await engine.record_usage(actual("request-2"))
    assert not (await engine.check(check("request-3")))["allowed"]


async def test_usage_record_is_durable_first_idempotent_and_conflict_checked(
    engine: Engine,
) -> None:
    await engine.check(check())
    first = await engine.record_usage(actual())
    replay = await engine.record_usage(actual())
    assert first["event"] == replay["event"]
    assert first["replayed"] is False and replay["replayed"] is True
    assert len(await engine.repository.list("usage_v2")) == 1

    with pytest.raises(Conflict, match="different provider usage"):
        await engine.record_usage(
            UsageRecordRequest(
                request_id="request-1",
                status="actual",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )


async def test_usage_commit_survives_redis_loss_and_duplicate_writers_charge_once(
    engine: Engine,
) -> None:
    await engine.check(check())
    counters = engine.counters
    assert isinstance(counters, MemoryCounters)
    counters.ready = False
    results = await asyncio.gather(engine.record_usage(actual()), engine.record_usage(actual()))
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert len(await engine.repository.list("usage_v2")) == 1
    with pytest.raises(OSError):
        await engine.check(check("next"))


async def test_unknown_usage_is_explicit_and_never_charged_as_zero(engine: Engine) -> None:
    await engine.check(check())
    result = await engine.record_usage(
        UsageRecordRequest(request_id="request-1", status="usage_unknown")
    )
    event = result["event"]
    assert event["status"] == "usage_unknown"
    assert event["input_tokens"] is None
    assert event["cost_micro_usd"] is None
    rows = await engine.chargeback("tenant-1", event["month"], "user-1")
    assert len(rows) == 1
    assert rows[0]["unknown_requests"] == 1
    assert rows[0]["cost_micro_usd"] is None
    assert rows[0]["input_tokens"] is None


async def test_malformed_provider_usage_is_durably_downgraded_to_unknown(engine: Engine) -> None:
    await engine.check(check())
    result = await engine.record_usage(
        UsageRecordRequest(
            request_id="request-1",
            status="actual",
            provider_usage={"prompt_tokens": "not-a-count"},
        )
    )
    assert result["event"]["status"] == "usage_unknown"
    assert result["event"]["cost_micro_usd"] is None
    assert result["event"]["input_tokens"] is None
    replay = await engine.record_usage(
        UsageRecordRequest(
            request_id="request-1",
            status="actual",
            provider_usage={"prompt_tokens": "not-a-count"},
        )
    )
    assert replay["replayed"] is True


async def test_usage_outside_snapshotted_model_price_bounds_is_unknown(engine: Engine) -> None:
    engine.settings.model_registry = {
        "openai-chat:model-1": ModelDeployment(
            api_protocol="openai-chat",
            endpoint="https://models.example.com",
            path="/openai/deployments/model-1/chat/completions",
            model="model-1",
            audience="https://cognitiveservices.azure.com",
            api_version="2025-01-01-preview",
            price_version="v1",
            max_input_tokens=5,
            max_output_tokens=20,
        )
    }
    await engine.check(check())
    result = await engine.record_usage(actual())
    assert result["event"]["status"] == "usage_unknown"
    assert result["event"]["cost_micro_usd"] is None
    assert result["event"]["input_tokens"] is None
    assert result["event"]["output_tokens"] is None


async def test_counter_projection_rebuilds_from_the_authoritative_ledger(engine: Engine) -> None:
    counters = engine.counters
    assert isinstance(counters, MemoryCounters)
    await engine.check(check())
    await engine.record_usage(actual())
    counters.counts.clear()
    denied = await engine.check(check("next"))
    assert denied["allowed"] is False
    assert counters.counts
    assert await engine.rebuild_counters() == 1


async def test_projection_failure_after_durable_write_is_repaired_on_next_check(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await engine.check(check())

    async def fail_projection(records):
        raise OSError("simulated crash gap")

    monkeypatch.setattr(engine.counters, "project", fail_projection)
    recorded = await engine.record_usage(actual())
    assert recorded["event"]["cost_micro_usd"] == 100
    assert len(await engine.repository.list("usage_v2")) == 1
    monkeypatch.undo()
    assert not (await engine.check(check("next")))["allowed"]


async def test_unassigned_principal_and_missing_price_fail_closed(engine: Engine) -> None:
    with pytest.raises(ValueError, match="unassigned"):
        await engine.check(check("unknown-user", principal_id="intruder"))
    await engine.repository.mutate("prices", "price-1", None, {"id": "audit-1"})
    with pytest.raises(ValueError, match="price card"):
        await engine.check(check("no-price"))


async def test_legacy_application_data_is_not_reinterpreted_as_user_budgets(
    engine: Engine,
) -> None:
    await engine.repository.create(
        "assignments",
        "legacy-app-assignment",
        {
            "id": "legacy-app-assignment",
            "tenant_id": "tenant-1",
            "subscription_id": "old-apim-app",
            "policy_ids": ["legacy-policy"],
        },
    )
    await engine.repository.create(
        "usage",
        "legacy-app-usage",
        {
            "id": "legacy-app-usage",
            "kind": "usage",
            "tenant_id": "tenant-1",
            "principal_id": "user-1",
            "data": {"cost_micro_usd": 999_999, "status": "actual"},
        },
    )

    admitted = await engine.check(check())
    assert admitted["allowed"] is True
    assert len(await engine.usage("tenant-1", "user-1", admin=False)) == 0
    assert [row["id"] for row in await engine.configuration("assignments")] == ["assignment-1"]
