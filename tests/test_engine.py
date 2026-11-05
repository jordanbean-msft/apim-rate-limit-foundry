import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Price, Reserve, Settle, Usage
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
        "model": "read",
    }
    assert (await engine.bind_operation(binding))["allowed"]
    assert (await engine.bind_operation(binding))["allowed"]
    check = {k: v for k, v in binding.items() if k != "reservation_id"}
    assert (await engine.check_operation(check))["allowed"]
    assert not (await engine.check_operation({**check, "tenant_id": "other"}))["allowed"]
    with pytest.raises(Conflict):
        await engine.bind_operation({**binding, "principal_id": "other"})


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
