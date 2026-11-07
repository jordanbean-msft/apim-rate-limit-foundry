import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.engine import Engine, event
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService
from apim_rate_limit_foundry.stores.contracts import Conflict, RecoveryRequired
from apim_rate_limit_foundry.stores.memory import MemoryCounters


async def test_concurrent_idempotency_and_all_policies_atomic(
    engine: Engine, request_body: Reserve
) -> None:
    repeated = await asyncio.gather(*(engine.reserve(request_body) for _ in range(30)))
    assert all(r.allowed for r in repeated)
    assert len({r.reservation_id for r in repeated}) == 1
    assert list(engine.counters.counts.values()) == [100]
    await engine.repository.create(
        "policies",
        "request-cap",
        {
            "id": "request-cap",
            "name": "Requests",
            "service": "foundry",
            "subscription_id": "*",
            "limit": 1,
            "period": "hour",
            "metric": "requests",
        },
    )
    second = await engine.reserve(request_body.model_copy(update={"request_id": "second"}))
    assert second.allowed
    counts_before = dict(engine.counters.counts)
    denied = await asyncio.gather(
        *(
            engine.reserve(request_body.model_copy(update={"request_id": f"denied-{i}"}))
            for i in range(20)
        )
    )
    assert not any(d.allowed for d in denied)
    assert engine.counters.counts == counts_before
    assert denied[0].headers["Retry-After"]


async def test_application_budget_shares_across_actors_and_isolates_subscriptions(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
) -> None:
    bounded = policy.model_copy(update={"limit": 150})
    await engine.repository.mutate(
        "policies", policy.id, bounded.model_dump(mode="json"), {"id": "app-budget"}
    )
    first = await engine.reserve(request_body.model_copy(update={"request_id": "first"}))
    repeated_by_other_actor = await engine.reserve(
        request_body.model_copy(update={"principal_id": "user-2", "request_id": "first"})
    )
    second_actor_request = await engine.reserve(
        request_body.model_copy(update={"principal_id": "user-2", "request_id": "second"})
    )
    isolated_application = await engine.reserve(
        request_body.model_copy(update={"request_id": "other-app", "subscription_id": "app-2"})
    )

    assert first.allowed and repeated_by_other_actor.allowed
    assert first.reservation_id == repeated_by_other_actor.reservation_id
    assert not second_actor_request.allowed
    assert isolated_application.allowed
    assert sorted(engine.counters.counts.values()) == [100, 100]
    assert (await engine.repository.get("intents", first.reservation_id))["data"]["request"][
        "principal_id"
    ] == "user-1"


async def test_legacy_user_policy_is_not_widened_to_applications(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
) -> None:
    legacy = policy.model_dump(mode="json")
    legacy.pop("subscription_id")
    legacy["principal_id"] = "user-1"
    await engine.repository.mutate("policies", policy.id, legacy, {"id": "legacy-policy"})

    with pytest.raises(ValueError, match="No matching policy"):
        await engine.reserve(request_body)
    assert not engine.counters.counts


async def test_legacy_liabilities_recover_outside_application_counter_and_reports(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
    price: Price,
) -> None:
    legacy_id = digest(request_body.tenant_id, request_body.principal_id, request_body.request_id)
    legacy_request = request_body.model_dump(mode="json")
    legacy_request["subscription_id"] = None
    expired_reset = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    legacy_debit = {
        "key": "legacy-user-counter-v1",
        "policy_id": policy.id,
        "metric": "cost",
        "amount": 100,
        "limit": 300,
        "reset_at": expired_reset,
    }
    intent_data = {
        "request": legacy_request,
        "fingerprint": "legacy-fingerprint",
        "debits": [legacy_debit],
        "price": price.model_dump(mode="json"),
        "decision": {"allowed": True, "reason": "reserved"},
    }
    await engine.repository.create(
        "intents",
        legacy_id,
        event("intent", legacy_id, request_body.tenant_id, request_body.principal_id, intent_data),
    )
    await engine.repository.create(
        "usage",
        legacy_id,
        event(
            "reservation",
            legacy_id,
            request_body.tenant_id,
            request_body.principal_id,
            {
                **intent_data,
                "allowed": True,
                "status": "reserved",
            },
        ),
    )

    await engine.recover()
    assert engine.counters.counts == {"legacy-user-counter-v1": 100}
    assert (await engine.reserve(request_body)).allowed
    assert sorted(engine.counters.counts.values()) == [100, 100]
    assert await engine.reconcile() == 1
    legacy_settlement = await engine.repository.get("settlements", legacy_id)
    assert legacy_settlement is not None and "subscription_id" not in legacy_settlement
    summary = await UsageSummaryService(engine.repository).summarize(
        "day", request_body.tenant_id, request_body.principal_id, True
    )
    assert len(summary) == 1 and summary[0].subscription_id == request_body.subscription_id
    usage_report = await engine.report("usage", request_body.tenant_id, "admin", True)
    assert next(row for row in usage_report if row["id"] == legacy_id)["accounting_scope"] == (
        "legacy_user"
    )


async def test_settlement_refunds_only_known_actual_usage(
    engine: Engine, request_body: Reserve
) -> None:
    decision = await engine.reserve(request_body)
    actual = Settle(
        reservation_id=decision.reservation_id,
        usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
        status="actual",
    )
    await asyncio.gather(*(engine.settle(actual) for _ in range(15)))
    assert list(engine.counters.counts.values()) == [18]
    with pytest.raises(Conflict):
        await engine.settle(
            actual.model_copy(update={"usage": Usage(input_tokens=0, output_tokens=0)})
        )
    with pytest.raises(ValueError, match="missing"):
        await engine.settle(actual.model_copy(update={"usage": Usage()}))
    report = await engine.report("usage", "tenant-1", "user-1", False)
    assert report[0]["data"]["estimated"] is False
    assert report[0]["data"]["debits"][0]["amount"] == 18


async def test_missing_usage_is_not_zero(engine: Engine, request_body: Reserve) -> None:
    decision = await engine.reserve(request_body)
    with pytest.raises(ValueError, match="missing"):
        await engine.settle(
            Settle(reservation_id=decision.reservation_id, usage=Usage(), status="actual")
        )
    assert list(engine.counters.counts.values()) == [100]
    await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            usage=Usage(input_tokens=0, output_tokens=0),
            status="actual",
        )
    )
    assert list(engine.counters.counts.values()) == [0]


async def test_missing_cached_usage_keeps_conservative_pricing_visibly_estimated(
    engine: Engine,
    request_body: Reserve,
) -> None:
    missing = await engine.reserve(request_body)
    settlement = await engine.settle(
        Settle(
            reservation_id=missing.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2),
        )
    )
    assert settlement["data"]["estimated"]
    assert settlement["data"]["cached_input_reported"] is False
    with pytest.raises(Conflict):
        await engine.settle(
            Settle(
                reservation_id=missing.reservation_id,
                status="actual",
                usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=0),
            )
        )
    explicit = await engine.reserve(request_body.model_copy(update={"request_id": "explicit-zero"}))
    settlement = await engine.settle(
        Settle(
            reservation_id=explicit.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=0),
        )
    )
    assert not settlement["data"]["estimated"]
    assert settlement["data"]["cached_input_reported"] is True
    assert sorted(engine.counters.counts.values()) == [48]


async def test_unknown_cached_usage_never_refunds_the_higher_possible_input_rate(
    engine: Engine,
    request_body: Reserve,
    price: Price,
) -> None:
    expensive_cached = price.model_copy(
        update={"cached_input_per_million": price.output_per_million}
    )
    await engine.repository.mutate(
        "prices", price.id, expensive_cached.model_dump(mode="json"), {"id": "price-change"}
    )
    decision = await engine.reserve(request_body)
    settlement = await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2),
        )
    )
    assert settlement["data"]["estimated"]
    assert list(engine.counters.counts.values()) == [40]


async def test_streams_and_release_retain_conservative_debit(
    engine: Engine, request_body: Reserve
) -> None:
    decision = await engine.reserve(request_body.model_copy(update={"streaming": True}))
    await engine.release(decision.reservation_id)
    assert list(engine.counters.counts.values()) == [100]
    assert (await engine.repository.list("reconciliation"))[0]["data"]["estimated"]
    with pytest.raises(ValueError, match="hard bound"):
        await engine.settle(
            Settle(
                reservation_id=decision.reservation_id,
                status="actual",
                usage=Usage(input_tokens=10, output_tokens=21),
            )
        )


async def test_storage_failure_does_not_grant_admission(
    engine: Engine, request_body: Reserve
) -> None:
    engine.repository.fail = True
    with pytest.raises(OSError):
        await engine.reserve(request_body)
    assert not engine.counters.counts
    engine.repository.fail = False
    original_create = engine.repository.create

    async def failing_create(collection: str, record_id: str, record: dict) -> dict:
        if collection == "usage":
            raise OSError("Durable event failed after Redis")
        return await original_create(collection, record_id, record)

    engine.repository.create = failing_create
    with pytest.raises(OSError):
        await engine.reserve(request_body)
    assert list(engine.counters.counts.values()) == [100]
    engine.repository.create = original_create
    engine.counters = MemoryCounters(ready=False)
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body)
    await engine.recover()
    assert list(engine.counters.counts.values()) == [100]
    assert not (await engine.reserve(request_body)).allowed


async def test_cache_loss_recovery_replays_settled_and_unresolved(
    engine: Engine, request_body: Reserve
) -> None:
    first = await engine.reserve(request_body)
    await engine.settle(
        Settle(
            reservation_id=first.reservation_id,
            usage=Usage(input_tokens=1, output_tokens=1),
            status="actual",
        )
    )
    await engine.reserve(
        request_body.model_copy(update={"request_id": "unresolved", "streaming": True})
    )
    engine.counters = MemoryCounters(ready=False)
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body.model_copy(update={"request_id": "new"}))
    await engine.recover()
    # The failed request's durable intent is retained conservatively too.
    assert list(engine.counters.counts.values()) == [206]
    assert (await engine.reserve(request_body)).allowed


async def test_repeated_recovery_keeps_uncertain_liabilities_but_not_proven_denials(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
) -> None:
    bounded = policy.model_copy(update={"limit": 200})
    await engine.repository.mutate(
        "policies",
        policy.id,
        bounded.model_dump(mode="json"),
        {"id": "bounded"},
    )
    engine.counters = MemoryCounters(ready=False)
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body)
    await engine.recover()
    uncertain = await engine.reserve(request_body)
    assert not uncertain.allowed and uncertain.reason == "recovered_conservatively"
    engine.counters = MemoryCounters(ready=False)
    await engine.recover()
    assert list(engine.counters.counts.values()) == [100]
    assert not (await engine.reserve(request_body)).allowed
    new_request = await engine.reserve(request_body.model_copy(update={"request_id": "new"}))
    assert new_request.allowed
    denied_request = request_body.model_copy(update={"request_id": "proven-denied"})
    denied = await engine.reserve(denied_request)
    assert not denied.allowed and denied.reason == "budget_exhausted"
    for _ in range(2):
        engine.counters = MemoryCounters(ready=False)
        await engine.recover()
        assert list(engine.counters.counts.values()) == [200]
        assert not (await engine.reserve(request_body)).allowed
        replay = await engine.reserve(denied_request)
        assert not replay.allowed and replay.reason == "budget_exhausted"


async def test_unknown_price_and_request_id_reuse_fail_closed(
    engine: Engine, request_body: Reserve
) -> None:
    with pytest.raises(ValueError, match="matching price"):
        await engine.reserve(request_body.model_copy(update={"model": "unknown"}))
    assert not engine.counters.counts
    await engine.reserve(request_body)
    with pytest.raises(Conflict):
        await engine.reserve(request_body.model_copy(update={"operation": "other"}))


async def test_document_poll_binding_and_scope(engine: Engine, request_body: Reserve) -> None:
    price = Price(
        id="di",
        service="document-intelligence",
        model="read",
        version="1",
        per_page="0.01",
        per_request="0",
    )
    await engine.repository.create("prices", "di", price.model_dump(mode="json"))
    await engine.repository.create(
        "policies",
        "di",
        {
            "id": "di",
            "name": "DI",
            "service": "document-intelligence",
            "subscription_id": "*",
            "limit": 5,
            "period": "day",
            "metric": "pages",
        },
    )
    decision = await engine.reserve(
        request_body.model_copy(
            update={
                "service": "document-intelligence",
                "model": "read",
                "usage": Usage(pages=5),
                "document_bound_verified": True,
            }
        )
    )
    binding = {
        "operation_id": str(uuid4()),
        "reservation_id": decision.reservation_id,
        "tenant_id": request_body.tenant_id,
        "principal_id": request_body.principal_id,
        "subscription_id": request_body.subscription_id,
        "model": "read",
    }
    assert (await engine.bind_operation(binding))["allowed"]
    assert (await engine.bind_operation(binding))["allowed"]
    check = {k: v for k, v in binding.items() if k != "reservation_id"}
    assert (await engine.check_operation(check))["allowed"]
    assert (await engine.check_operation({**check, "principal_id": "different-user"}))["allowed"]
    assert not (await engine.check_operation({**check, "tenant_id": "other"}))["allowed"]
    assert not (await engine.check_operation({**check, "subscription_id": "another-app"}))[
        "allowed"
    ]
    other_application = await engine.reserve(
        request_body.model_copy(
            update={
                "request_id": "document-other-app",
                "subscription_id": "another-app",
                "service": "document-intelligence",
                "model": "read",
                "usage": Usage(pages=5),
                "document_bound_verified": True,
            }
        )
    )
    other_binding = {
        **binding,
        "reservation_id": other_application.reservation_id,
        "subscription_id": "another-app",
    }
    assert (await engine.bind_operation(other_binding))["allowed"]
    other_check = {key: value for key, value in other_binding.items() if key != "reservation_id"}
    assert (await engine.check_operation(other_check))["allowed"]
    assert (await engine.bind_operation({**binding, "principal_id": "other"}))["allowed"]


async def test_timer_finalizes_expired_stream_without_refund(
    engine: Engine, request_body: Reserve
) -> None:
    decision = await engine.reserve(request_body.model_copy(update={"streaming": True}))
    record = engine.repository.records["intents", decision.reservation_id]
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    for debit in record["data"]["debits"]:
        debit["reset_at"] = past
    assert await engine.reconcile() == 1
    assert await engine.reconcile() == 0
    assert list(engine.counters.counts.values()) == [100]


async def test_recovery_failure_keeps_gate_closed(engine: Engine, request_body: Reserve) -> None:
    await engine.reserve(request_body)
    engine.repository.fail = True
    with pytest.raises(OSError):
        await engine.recover()
    engine.repository.fail = False
    with pytest.raises(RecoveryRequired):
        await engine.reserve(request_body.model_copy(update={"request_id": "new"}))
    with pytest.raises(Conflict):
        await engine.recover()


async def test_expired_intent_cannot_admit_against_an_old_window(
    engine: Engine,
    request_body: Reserve,
) -> None:
    decision = await engine.reserve(request_body)
    intent = engine.repository.records["intents", decision.reservation_id]
    intent["data"]["debits"][0]["reset_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    assert not (await engine.reserve(request_body)).allowed


async def test_metric_edit_does_not_mix_liabilities_or_settlement_deltas(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
) -> None:
    original = await engine.reserve(request_body)
    changed = policy.model_copy(update={"metric": "requests", "limit": 2})
    await engine.repository.mutate(
        "policies", policy.id, changed.model_dump(mode="json"), {"id": "metric-change"}
    )
    for request_id in ("new-metric-1", "new-metric-2"):
        assert (
            await engine.reserve(request_body.model_copy(update={"request_id": request_id}))
        ).allowed
    await engine.settle(
        Settle(
            reservation_id=original.reservation_id,
            status="actual",
            usage=Usage(input_tokens=2, output_tokens=1),
        )
    )
    assert sorted(engine.counters.counts.values()) == [2, 8]
    assert not (
        await engine.reserve(request_body.model_copy(update={"request_id": "denied"}))
    ).allowed


@pytest.mark.parametrize("minute_limit", [1, 100])
async def test_denial_reports_blocking_policy_reset_not_shorter_unblocked_window(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
    frozen_accounting_time: datetime,
    minute_limit: int,
) -> None:
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
            "subscription_id": "*",
            "limit": minute_limit,
            "period": "minute",
            "metric": "requests",
        },
    )
    first = await engine.reserve(request_body)
    assert first.allowed
    assert first.remaining_by_policy == {"policy-1": 0, "minute": minute_limit - 1}
    denied = await engine.reserve(request_body.model_copy(update={"request_id": "month-denied"}))
    assert not denied.allowed
    assert denied.reset_at == "2030-12-01T00:00:00+00:00"
    assert denied.retry_after > 60
    assert set(denied.matched_policy_ids) == {"policy-1", "minute"}
    assert set(denied.denied_policy_ids) == (
        {"policy-1", "minute"} if minute_limit == 1 else {"policy-1"}
    )
    assert "policy-1" in denied.headers["X-RateLimit-Denied-Policies"]
    await engine.recover()
    replay = await engine.reserve(request_body.model_copy(update={"request_id": "month-denied"}))
    assert replay.reset_at == denied.reset_at
    assert replay.denied_policy_ids == denied.denied_policy_ids
