from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService


async def test_rollups_charge_each_admission_once_across_rules_and_late_settlement(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
) -> None:
    second_rule = policy.model_copy(update={"id": "second-cost", "limit": 100})
    await engine.repository.create("policies", second_rule.id, second_rule.model_dump(mode="json"))
    first = await engine.reserve(request_body)
    await engine.reserve(request_body)
    denied = await engine.reserve(request_body.model_copy(update={"request_id": "denied"}))
    assert not denied.allowed
    service = UsageSummaryService(engine.repository)
    before = (await service.summarize("day", "tenant-1", "user-1", False))[0]
    assert before.request_count == 2
    assert before.admitted_requests == before.denied_requests == before.estimated_requests == 1
    assert before.cost_micro_usd == 100
    await engine.settle(
        Settle(
            reservation_id=first.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
        )
    )
    after = (await service.summarize("day", "tenant-1", "user-1", False))[0]
    assert after.id == before.id
    assert after.request_count == 2
    assert after.cost_micro_usd == 18
    assert after.estimated_requests == 0
    assert (after.input_tokens, after.output_tokens, after.cached_input_tokens) == (8, 2, 4)
    assert await service.summarize("day", "tenant-1", "user-1", False) == [after]


async def test_rollups_preserve_conservative_streams_even_with_zero_conservative_payload(
    engine: Engine,
    request_body: Reserve,
) -> None:
    decision = await engine.reserve(request_body.model_copy(update={"streaming": True}))
    await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="conservative",
            usage=Usage(input_tokens=0, output_tokens=0),
        )
    )
    summary = (
        await UsageSummaryService(engine.repository).summarize(
            "hour",
            "tenant-1",
            "user-1",
            False,
        )
    )[0]
    assert summary.cost_micro_usd == 100
    assert summary.estimated_requests == 1
    assert (summary.input_tokens, summary.output_tokens) == (10, 20)


async def test_rollups_mark_unknown_cached_usage_and_work_without_cost_rules(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
    price: Price,
) -> None:
    request_rule = policy.model_copy(update={"metric": "requests"})
    await engine.repository.mutate(
        "policies", policy.id, request_rule.model_dump(mode="json"), {"id": "request-rule"}
    )
    expensive_cached = price.model_copy(
        update={"cached_input_per_million": price.output_per_million}
    )
    await engine.repository.mutate(
        "prices", price.id, expensive_cached.model_dump(mode="json"), {"id": "price-change"}
    )
    decision = await engine.reserve(request_body)
    await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2),
        )
    )
    summary = (
        await UsageSummaryService(engine.repository).summarize(
            "day",
            "tenant-1",
            "user-1",
            False,
        )
    )[0]
    assert summary.cost_micro_usd == 40
    assert summary.estimated_requests == 1


async def test_hour_and_day_rollups_use_utc_admission_not_settlement_time(
    engine: Engine,
    request_body: Reserve,
) -> None:
    start = datetime(2030, 11, 5, 23, 30, tzinfo=UTC)
    instants = [start, start + timedelta(minutes=5), start + timedelta(hours=1)]
    for index, timestamp in enumerate(instants):
        with patch("apim_rate_limit_foundry.engine.datetime", wraps=datetime) as clock:
            clock.now.return_value = timestamp
            await engine.reserve(request_body.model_copy(update={"request_id": f"request-{index}"}))
    service = UsageSummaryService(engine.repository)
    hours = await service.summarize("hour", "tenant-1", "user-1", False)
    days = await service.summarize("day", "tenant-1", "user-1", False)
    assert [(row.start_at.hour, row.request_count, row.cost_micro_usd) for row in hours] == [
        (23, 2, 200),
        (0, 1, 100),
    ]
    assert [(row.start_at.day, row.request_count) for row in days] == [(5, 2), (6, 1)]
    assert all(row.start_at.tzinfo == UTC and row.end_at.tzinfo == UTC for row in hours + days)


async def test_summary_endpoint_scopes_explicit_application_assignment(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
) -> None:
    await engine.reserve(request_body)
    await engine.reserve(
        request_body.model_copy(update={"tenant_id": "other-tenant", "request_id": "other-tenant"})
    )
    await engine.reserve(
        request_body.model_copy(update={"principal_id": "other-user", "request_id": "other-user"})
    )
    await engine.reserve(
        request_body.model_copy(update={"subscription_id": "other-app", "request_id": "other-app"})
    )
    reader = {
        "X-Local-Tenant-Id": "tenant-1",
        "X-Local-Principal-Id": "user-1",
        "X-Local-Roles": "RateLimit.Reader",
    }
    admin = {**reader, "X-Local-Roles": "RateLimit.Admin"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/usage/summary")).status_code == 401
        own = (await client.get("/api/usage/summary?period=hour", headers=reader)).json()
        all_rows = (await client.get("/api/usage/summary?period=day", headers=admin)).json()
        events = (await client.get("/api/usage", headers=reader)).json()
        assert len(own) == 1 and len(events) == 2
        assert len(all_rows) == 3
        assert own[0]["tenant_id"] == "tenant-1" and own[0]["subscription_id"] == "app-1"
        assert own[0]["request_count"] == 2
        assert own[0]["cost_micro_usd"] == 200
        assert events[0]["kind"] == "reservation" and "data" in events[0]
        assert (
            await client.get("/api/usage/summary?period=month", headers=reader)
        ).status_code == 422


async def test_rollups_separate_services_models_and_service_units(
    engine: Engine,
    request_body: Reserve,
    price: Price,
) -> None:
    await engine.reserve(request_body)
    other_model = price.model_copy(update={"id": "other-model", "model": "other-model"})
    await engine.repository.create("prices", other_model.id, other_model.model_dump(mode="json"))
    await engine.reserve(
        request_body.model_copy(update={"request_id": "other", "model": "other-model"})
    )
    for service, model, usage, rate in (
        ("document-intelligence", "read", Usage(pages=3), {"per_page": "0.01"}),
        ("language", "sentiment", Usage(text_records=2), {"per_text_record": "0.001"}),
    ):
        card = Price(id=service, service=service, model=model, version="1", per_request="0", **rate)
        rule = Policy(
            id=service,
            name=service,
            service=service,
            subscription_id="*",
            period="day",
            metric="requests",
            limit=10,
        )
        await engine.repository.create("prices", card.id, card.model_dump(mode="json"))
        await engine.repository.create("policies", rule.id, rule.model_dump(mode="json"))
        decision = await engine.reserve(
            request_body.model_copy(
                update={
                    "request_id": service,
                    "service": service,
                    "model": model,
                    "usage": usage,
                    "document_bound_verified": service == "document-intelligence",
                }
            )
        )
        if service == "document-intelligence":
            await engine.settle(
                Settle(
                    reservation_id=decision.reservation_id,
                    status="actual",
                    usage=Usage(pages=2),
                )
            )
    summaries = await UsageSummaryService(engine.repository).summarize(
        "day",
        "tenant-1",
        "user-1",
        False,
    )
    grouped = {(row.service, row.model): row for row in summaries}
    assert len(grouped) == 4
    assert grouped["document-intelligence", "read"].pages == 2
    assert grouped["document-intelligence", "read"].cost_micro_usd == 20000
    assert grouped["document-intelligence", "read"].estimated_requests == 0
    assert grouped["language", "sentiment"].text_records == 2
    assert grouped["language", "sentiment"].cost_micro_usd == 2000
