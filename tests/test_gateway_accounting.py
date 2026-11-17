import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from apim_rate_limit_foundry.accounting import usage_partition, utc_month
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.models.budget import Budget
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.price import Price
from apim_rate_limit_foundry.stores.contracts import Conflict, InvalidConfiguration
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from tests.fakes import persisted_usage

# Host-wide default ceilings (131072 input, 32768 output) at the fixture's 2/4 USD per million.
UPPER_BOUND = 131072 * 2 + 32768 * 4


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
    gateway: GatewayServices,
) -> None:
    admitted = await gateway.admission.check(check())
    assert admitted["allowed"] is True
    assert admitted["denied_budget_ids"] == []

    recorded = await gateway.usage.record(actual())
    assert recorded["replayed"] is False
    assert recorded["event"]["cost_micro_usd"] == 100
    assert recorded["event"]["business_unit"] == "BU-ENG"
    assert recorded["event"]["cost_center"] == "CC-100"

    denied = await gateway.admission.check(check("request-2"))
    assert denied["allowed"] is False
    assert set(denied["denied_budget_ids"]) == {
        "budget-user",
        "budget-team",
        "budget-department",
    }


async def test_check_is_idempotent_conflict_protected_and_completed_ids_rejected(
    gateway: GatewayServices,
) -> None:
    first = await gateway.admission.check(check())
    replay = await gateway.admission.check(check())
    assert first == replay
    with pytest.raises(Conflict, match="different request"):
        await gateway.admission.check(check("request-1", model="other"))

    await gateway.usage.record(actual())
    with pytest.raises(Conflict, match="Completed"):
        await gateway.admission.check(check())


async def test_only_the_first_usage_record_is_exported(
    gateway: GatewayServices, publisher: AsyncMock
) -> None:
    await gateway.admission.check(check())

    first = await gateway.usage.record(actual())
    replay = await gateway.usage.record(actual())
    await gateway.background.flush()

    assert replay["replayed"] is True
    publisher.publish.assert_awaited_once_with(first["event"])


async def test_post_request_soft_cap_allows_in_flight_requests_to_overshoot(
    gateway: GatewayServices,
) -> None:
    checks = await asyncio.gather(
        gateway.admission.check(check("inflight-1")), gateway.admission.check(check("inflight-2"))
    )
    assert all(result["allowed"] for result in checks)
    await gateway.usage.record(actual("inflight-1"))
    await gateway.usage.record(actual("inflight-2"))
    next_request = await gateway.admission.check(check("next"))
    assert next_request["allowed"] is False


@pytest.mark.parametrize("subject_type", ["user", "team", "department", None])
async def test_each_configured_zero_budget_blocks_but_unconfigured_levels_do_not(
    gateway: GatewayServices, subject_type: str | None
) -> None:
    for kind in ("user", "team", "department"):
        budget_id = f"budget-{kind}"
        budget = await gateway.repository.get("budgets", budget_id)
        assert budget is not None
        budget.update(enabled=kind == subject_type, limit_micro_usd=0)
        await gateway.repository.mutate("budgets", budget_id, budget, {"id": f"audit-{kind}"})

    decision = await gateway.admission.check(check())

    assert decision["allowed"] is (subject_type is None)
    assert decision["denied_budget_ids"] == ([f"budget-{subject_type}"] if subject_type else [])


async def test_month_rollover_resets_budgets_and_preserves_inflight_accounting_month(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apim_rate_limit_foundry.engine.admission_service.utc_month",
        lambda: utc_month(datetime(2030, 12, 31, 23, 59, tzinfo=UTC)),
    )
    await gateway.admission.check(check("completed-december"))
    await gateway.admission.check(check("inflight-december"))
    await gateway.usage.record(actual("completed-december"))
    assert not (await gateway.admission.check(check("denied-december")))["allowed"]
    monkeypatch.setattr(
        "apim_rate_limit_foundry.engine.admission_service.utc_month",
        lambda: utc_month(datetime(2031, 1, 1, tzinfo=UTC)),
    )

    late_record = await gateway.usage.record(actual("inflight-december"))
    january = await gateway.admission.check(check("fresh-january"))

    assert late_record["event"]["month"] == "2030-12"
    assert january["allowed"]
    await gateway.background.flush()
    assert (
        sum(
            row["cost_micro_usd"]
            for row in await gateway.reports.chargeback("tenant-1", "2030-12", None)
        )
        == 200
    )
    assert await gateway.reports.chargeback("tenant-1", "2031-01", None) == []


async def test_wildcard_budget_accumulates_spend_across_models(gateway: GatewayServices) -> None:
    for kind in ("user", "team", "department"):
        budget_id = f"budget-{kind}"
        budget = await gateway.repository.get("budgets", budget_id)
        assert budget is not None
        budget["limit_micro_usd"] = 200
        await gateway.repository.mutate("budgets", budget_id, budget, {"id": f"audit-{kind}"})
    second_price = Price(
        id="price-2",
        model="model-2",
        version="v1",
        input_per_million="2",
        cached_input_per_million="0.5",
        output_per_million="4",
    )
    await gateway.repository.create("prices", second_price.id, second_price.model_dump(mode="json"))
    await gateway.admission.check(check())
    await gateway.usage.record(actual())
    second = check("request-2", model="model-2")
    assert (await gateway.admission.check(second))["allowed"]
    await gateway.usage.record(actual("request-2"))
    assert not (await gateway.admission.check(check("request-3")))["allowed"]


async def test_usage_record_is_redis_first_idempotent_and_conflict_checked(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    first = await gateway.usage.record(actual())
    replay = await gateway.usage.record(actual())
    assert first["event"] == replay["event"]
    assert first["replayed"] is False and replay["replayed"] is True
    await gateway.background.flush()
    assert len(await persisted_usage(gateway)) == 1

    with pytest.raises(Conflict, match="different provider usage"):
        await gateway.usage.record(
            UsageRecordRequest(
                request_id="request-1",
                status="actual",
                provider_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )
        )


async def test_usage_requires_redis_even_when_table_is_available(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    counters = gateway.counters
    assert isinstance(counters, MemoryCounters)
    counters.ready = False
    with pytest.raises(OSError):
        await gateway.usage.record(actual())
    with pytest.raises(OSError):
        await gateway.admission.check(check("next"))


async def test_unknown_usage_is_explicit_and_charged_the_pinned_upper_bound(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    result = await gateway.usage.record(
        UsageRecordRequest(request_id="request-1", status="usage_unknown")
    )
    event = result["event"]
    assert event["status"] == "usage_unknown"
    assert event["input_tokens"] is None
    assert event["cost_basis"] == "estimated_upper_bound"
    assert event["cost_micro_usd"] == UPPER_BOUND
    assert not (await gateway.admission.check(check("next")))["allowed"]
    await gateway.background.flush()
    rows = await gateway.reports.chargeback("tenant-1", event["month"], "user-1")
    assert len(rows) == 1
    assert rows[0]["unknown_requests"] == 1
    assert rows[0]["cost_micro_usd"] == UPPER_BOUND
    assert rows[0]["cost_basis"] == "estimated_upper_bound"
    assert rows[0]["input_tokens"] is None


async def test_malformed_provider_usage_is_durably_downgraded_to_charged_unknown(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    malformed = UsageRecordRequest(
        request_id="request-1", status="actual", provider_usage={"prompt_tokens": "not-a-count"}
    )
    result = await gateway.usage.record(malformed)
    assert result["event"]["status"] == "usage_unknown"
    assert result["event"]["cost_micro_usd"] == UPPER_BOUND
    assert result["event"]["input_tokens"] is None
    replay = await gateway.usage.record(malformed)
    assert replay["replayed"] is True


def pin_registry(gateway: GatewayServices, max_input: int, max_output: int) -> None:
    gateway.settings.model_registry = {
        "openai-chat:model-1": ModelDeployment(
            api_protocol="openai-chat",
            endpoint="https://models.example.com",
            path="/openai/deployments/model-1/chat/completions",
            model="model-1",
            audience="https://cognitiveservices.azure.com",
            api_version="2025-01-01-preview",
            price_version="v1",
            max_input_tokens=max_input,
            max_output_tokens=max_output,
        )
    }


async def test_usage_above_pinned_model_bounds_is_priced_and_flagged(
    gateway: GatewayServices, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("apim_rate_limit_foundry"), "propagate", True)
    pin_registry(gateway, max_input=5, max_output=20)
    await gateway.admission.check(check())
    result = await gateway.usage.record(actual())
    event = result["event"]
    assert event["status"] == "actual"
    assert event["out_of_bounds"] is True
    assert event["cost_basis"] == "provider_usage"
    assert (event["input_tokens"], event["output_tokens"]) == (10, 20)
    assert event["cost_micro_usd"] == 100
    assert "usage_out_of_bounds" in caplog.text


async def test_unknown_usage_uses_the_bounds_pinned_at_admission(gateway: GatewayServices) -> None:
    pin_registry(gateway, max_input=1000, max_output=500)
    await gateway.admission.check(check())
    gateway.settings.model_registry = {}
    result = await gateway.usage.record(
        UsageRecordRequest(request_id="request-1", status="usage_unknown")
    )
    assert result["event"]["cost_micro_usd"] == 1000 * 2 + 500 * 4


async def test_cache_write_tokens_are_priced_and_recorded(gateway: GatewayServices) -> None:
    price = Price(
        id="price-1",
        model="model-1",
        version="v1",
        input_per_million="2",
        cached_input_per_million="0.5",
        cache_write_per_million="2.5",
        output_per_million="4",
    )
    await gateway.configuration.save(
        "prices", "price-1", price.model_dump(mode="json"), "tenant-1", "admin"
    )
    await gateway.admission.check(check())
    result = await gateway.usage.record(
        UsageRecordRequest(
            request_id="request-1",
            status="actual",
            provider_usage={
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 20},
            },
        )
    )
    event = result["event"]
    assert event["cache_write_tokens"] == 20
    assert event["cost_micro_usd"] == 40 * 2 + 40 * 0.5 + 20 * 2.5 + 10 * 4


async def test_redis_counter_loss_resets_live_spend_without_a_ledger_rebuild(
    gateway: GatewayServices,
) -> None:
    counters = gateway.counters
    assert isinstance(counters, MemoryCounters)
    await gateway.admission.check(check())
    await gateway.usage.record(actual())
    counters.counts.clear()
    allowed = await gateway.admission.check(check("next"))
    assert allowed["allowed"] is True
    assert not counters.counts


async def test_warm_admission_and_usage_do_not_wait_for_table_io(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await gateway.admission.check(check("warmup"))
    await gateway.background.flush()
    release = asyncio.Event()
    started = asyncio.Event()
    blocked_write = AsyncMock(side_effect=lambda *args: None)

    async def write(*args):
        started.set()
        await release.wait()
        return args[-1]

    blocked_write.side_effect = write
    monkeypatch.setattr(gateway.repository, "create", blocked_write)
    no_reads = AsyncMock(side_effect=AssertionError("Table read on the warm path"))
    monkeypatch.setattr(gateway.repository, "get", no_reads)
    monkeypatch.setattr(gateway.repository, "list", no_reads)
    try:
        async with asyncio.timeout(1):
            assert (await gateway.admission.check(check()))["allowed"]
            await started.wait()
            assert blocked_write.await_count == 1
            recorded = await gateway.usage.record(actual())
            assert recorded["event"]["cost_micro_usd"] == 100
            assert not (await gateway.admission.check(check("next")))["allowed"]
        no_reads.assert_not_awaited()
    finally:
        release.set()
        await gateway.background.flush()


async def test_table_write_failure_does_not_change_live_budget(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(logging.getLogger("apim_rate_limit_foundry"), "propagate", True)
    await gateway.admission.check(check())
    await gateway.background.flush()
    monkeypatch.setattr(gateway.repository, "create", AsyncMock(side_effect=OSError("offline")))
    await gateway.usage.record(actual())
    await gateway.background.flush()
    assert not (await gateway.admission.check(check("next")))["allowed"]
    assert "background_write_failed" in caplog.text


async def test_concurrent_duplicate_usage_increments_hierarchy_only_once(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    results = await asyncio.gather(*(gateway.usage.record(actual()) for _ in range(10)))
    assert sum(not row["replayed"] for row in results) == 1
    statuses = await gateway.reports.budget_status("tenant-1", "user-1")
    assert all(row["spent_micro_usd"] == 100 for row in statuses)


async def test_config_api_invalidates_shared_cache(gateway: GatewayServices) -> None:
    assert (await gateway.admission.check(check()))["allowed"]
    budget = await gateway.repository.get("budgets", "budget-team")
    assert budget is not None
    budget["limit_micro_usd"] = 0
    await gateway.configuration.save("budgets", "budget-team", budget, "tenant-1", "admin")
    assert (await gateway.admission.check(check("updated")))["denied_budget_ids"] == ["budget-team"]


async def test_unassigned_principal_and_missing_price_fail_closed(gateway: GatewayServices) -> None:
    with pytest.raises(ValueError, match="unassigned"):
        await gateway.admission.check(check("unknown-user", principal_id="intruder"))
    await gateway.repository.mutate("prices", "price-1", None, {"id": "audit-1"})
    await gateway.counters.invalidate_configuration()
    with pytest.raises(ValueError, match="price card"):
        await gateway.admission.check(check("no-price"))


async def test_legacy_application_data_is_not_reinterpreted_as_user_budgets(
    gateway: GatewayServices,
) -> None:
    await gateway.repository.create(
        "assignments",
        "legacy-app-assignment",
        {
            "id": "legacy-app-assignment",
            "tenant_id": "tenant-1",
            "subscription_id": "old-apim-app",
            "policy_ids": ["legacy-policy"],
        },
    )
    await gateway.repository.create(
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

    admitted = await gateway.admission.check(check())
    assert admitted["allowed"] is True
    assert len(await gateway.reports.usage("tenant-1", "user-1", admin=False)) == 0
    assert [row["id"] for row in await gateway.configuration.list("assignments")] == [
        "assignment-1"
    ]


async def test_invalid_current_schema_budget_is_logged_and_fails_closed(
    gateway: GatewayServices, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("apim_rate_limit_foundry"), "propagate", True)
    budget = await gateway.repository.get("budgets", "budget-team")
    assert budget is not None
    await gateway.repository.mutate(
        "budgets", "budget-team", {**budget, "limit_micro_usd": "free"}, {"id": "audit-bad"}
    )
    await gateway.counters.invalidate_configuration()

    with pytest.raises(InvalidConfiguration, match="budgets configuration record: budget-team"):
        await gateway.admission.check(check("fails-closed"))

    assert "configuration_record_invalid" in caplog.text
    assert await gateway.counters.request("fails-closed") is None


async def test_invalid_current_schema_record_can_be_replaced_or_deleted(
    gateway: GatewayServices,
) -> None:
    budget = await gateway.repository.get("budgets", "budget-team")
    assert budget is not None
    await gateway.repository.mutate(
        "budgets", "budget-team", {**budget, "limit_micro_usd": "free"}, {"id": "audit-bad"}
    )
    await gateway.repository.mutate(
        "budgets", "budget-user", {**budget, "id": "budget-user", "name": 7}, {"id": "audit-bad-2"}
    )

    await gateway.configuration.save("budgets", "budget-team", budget, "tenant-1", "admin")
    await gateway.configuration.delete("budgets", "budget-user", "tenant-1", "admin")

    assert {row["id"] for row in await gateway.configuration.list("budgets")} == {
        "budget-team",
        "budget-department",
    }


async def test_legacy_records_are_skipped_but_still_protected_from_replacement(
    gateway: GatewayServices,
) -> None:
    legacy = {"id": "legacy-budget", "tenant_id": "tenant-1", "application_id": "old", "hold": 5}
    await gateway.repository.create("budgets", "legacy-budget", legacy)

    assert "legacy-budget" not in {row["id"] for row in await gateway.configuration.list("budgets")}
    replacement = Budget(
        id="legacy-budget",
        tenant_id="tenant-1",
        name="new",
        subject_type="user",
        subject_id="user-1",
        limit_micro_usd=1,
    )
    with pytest.raises(Conflict, match="Legacy"):
        await gateway.configuration.save(
            "budgets", "legacy-budget", replacement.model_dump(mode="json"), "tenant-1", "admin"
        )
    with pytest.raises(Conflict, match="Legacy"):
        await gateway.configuration.delete("budgets", "legacy-budget", "tenant-1", "admin")


async def test_archived_multi_service_prices_are_skipped(gateway: GatewayServices) -> None:
    archived = {
        "id": "sample-language-v1",
        "service": "language",
        "model": "sentiment",
        "version": "sample-v1",
        "input_per_million": "0",
        "output_per_million": "0",
        "cached_input_per_million": "0",
        "per_text_record": "0.001",
    }
    await gateway.repository.create("prices", "sample-language-v1", archived)

    assert "sample-language-v1" not in {
        row["id"] for row in await gateway.configuration.list("prices")
    }


async def test_usage_history_is_read_from_the_tenant_month_partition_only(
    gateway: GatewayServices,
) -> None:
    await gateway.admission.check(check())
    await gateway.usage.record(actual())
    await gateway.background.flush()
    month = utc_month()[0]
    repository = gateway.repository
    assert isinstance(repository, MemoryRepository)
    row = (await persisted_usage(gateway))[0]
    await repository.create(
        "usage_v2",
        "other-tenant",
        {**row, "tenant_id": "tenant-2"},
        usage_partition("tenant-2", month),
    )
    await repository.create("usage_v2", "other-month", row, usage_partition("tenant-1", "2000-01"))
    await repository.create("usage_v2", "legacy", row)

    assert len(await gateway.reports.usage("tenant-1", "user-1", admin=False)) == 1
    assert len(await gateway.reports.usage("tenant-1", "user-1", admin=False, month=month)) == 1
    assert await gateway.reports.usage("tenant-1", "someone-else", admin=False) == []
    assert (
        len(await gateway.reports.usage("tenant-1", "someone-else", admin=True, month="2000-01"))
        == 1
    )
    assert len(await gateway.reports.chargeback("tenant-2", month, None)) == 1
    assert (
        sum(r["cost_micro_usd"] for r in await gateway.reports.chargeback("tenant-1", month, None))
        == 100
    )
    assert await gateway.reports.chargeback("tenant-1", "1999-12", None) == []
    assert await gateway.reports.chargeback("tenant-1", month, "someone-else") == []


async def test_chargeback_never_lists_the_whole_usage_collection(
    gateway: GatewayServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(gateway.repository, "list", listing)

    await gateway.reports.chargeback("tenant-1", "2030-01", None)
    await gateway.reports.usage("tenant-1", "user-1", admin=True, month="2030-01")

    assert [call.args for call in listing.await_args_list] == [
        ("usage_v2", "usage:tenant-1:2030-01")
    ] * 2


async def test_has_assignment_reports_enabled_single_assignments(gateway: GatewayServices) -> None:
    assert await gateway.admission.has_assignment("tenant-1", "user-1") is True
    assert await gateway.admission.has_assignment("tenant-1", "stranger") is False
    assert await gateway.admission.has_assignment("tenant-2", "user-1") is False
