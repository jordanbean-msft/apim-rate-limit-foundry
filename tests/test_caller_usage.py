from unittest.mock import AsyncMock

import httpx
import pytest

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.caller_reference import caller_ref
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.reports.caller_usage import CallerUsageService
from tests.test_api import ADMIN, GATEWAY, READER


def test_caller_reference_is_stable_tenant_bound_and_unambiguous() -> None:
    reference = caller_ref("tenant-1", "app-1")
    assert reference == "1aba06c41992186a7a25ee96d96e5f549355f12ece52cd6178d053b9d78b82ba"
    assert reference == caller_ref("tenant-1", "app-1")
    assert reference != caller_ref("other-tenant", "app-1")
    assert caller_ref("a:b", "c") != caller_ref("a", "b:c")
    assert caller_ref("a", "b") != caller_ref("b", "a")
    assert "tenant-1" not in reference and "user-1" not in reference
    with pytest.raises(ValueError, match="newline"):
        caller_ref("a\nb", "c")
    with pytest.raises(ValueError, match="newline"):
        caller_ref("a", "b\nc")


async def test_caller_totals_replace_cost_deduplicate_and_attribute_only_denied_rules(
    engine: Engine,
    request_body: Reserve,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = policy.model_copy(update={"id": "binding-rule", "limit": 100})
    await engine.repository.create("policies", rule.id, rule.model_dump(mode="json"))
    request = request_body.model_copy(update={"streaming": True})
    decision = await engine.reserve(request)
    await engine.reserve(request)
    denied = await engine.reserve(request.model_copy(update={"request_id": "denied"}))
    assert not denied.allowed
    report = CallerUsageService(engine.repository)
    before = (await report.summarize("day", "tenant-1", "user-1", False))[0]
    assert before.request_count == 2
    assert before.admitted_requests == before.denied_requests == before.estimated_requests == 1
    assert before.denied_policy_counts == {"binding-rule": 1}
    assert before.actual_cost_micro_usd == 0
    assert before.cost_micro_usd == before.conservative_cost_micro_usd == 100
    assert before.streaming and before.caller_ref == caller_ref("tenant-1", "app-1")

    actual = Settle(
        reservation_id=decision.reservation_id,
        status="actual",
        usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
    )
    await engine.settle(actual)
    await engine.settle(actual)
    original_list = engine.repository.list

    async def duplicated(collection: str) -> list[dict]:
        rows = await original_list(collection)
        return rows + rows if collection == "usage" else rows

    monkeypatch.setattr(engine.repository, "list", AsyncMock(side_effect=duplicated))
    after = (await report.summarize("day", "tenant-1", "user-1", False))[0]
    assert after.id == before.id
    assert after.request_count == 2 and after.denied_policy_counts == {"binding-rule": 1}
    assert after.cost_micro_usd == after.actual_cost_micro_usd == 18
    assert after.estimated_requests == after.conservative_cost_micro_usd == 0


async def test_caller_report_separates_streams_models_services_and_retains_liabilities(
    engine: Engine,
    request_body: Reserve,
    price: Price,
) -> None:
    streaming = await engine.reserve(request_body.model_copy(update={"streaming": True}))
    await engine.settle(
        Settle(
            reservation_id=streaming.reservation_id,
            status="actual",
            provider_usage={"prompt_tokens": 0},
        )
    )
    nonstream = await engine.reserve(request_body.model_copy(update={"request_id": "nonstream"}))
    await engine.settle(
        Settle(
            reservation_id=nonstream.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2),
        )
    )
    other_price = price.model_copy(update={"id": "other", "model": "other"})
    await engine.repository.create("prices", other_price.id, other_price.model_dump(mode="json"))
    await engine.reserve(request_body.model_copy(update={"request_id": "other", "model": "other"}))
    language_price = Price(
        id="language",
        service="language",
        model="sentiment",
        version="1",
        per_text_record="0.001",
        per_request="0",
    )
    language_policy = Policy(
        id="language",
        name="Language",
        service="language",
        subscription_id="*",
        period="day",
        metric="requests",
        limit=10,
    )
    await engine.repository.create(
        "prices", language_price.id, language_price.model_dump(mode="json")
    )
    await engine.repository.create(
        "policies", language_policy.id, language_policy.model_dump(mode="json")
    )
    await engine.reserve(
        request_body.model_copy(
            update={
                "request_id": "language",
                "service": "language",
                "model": "sentiment",
                "usage": Usage(text_records=2),
            }
        )
    )
    rows = await CallerUsageService(engine.repository).summarize(
        "hour", "tenant-1", "user-1", False
    )
    grouped = {(row.service, row.model, row.streaming): row for row in rows}
    assert len(grouped) == 4
    assert len({row.caller_ref for row in rows}) == 1
    pending = grouped["foundry", "model-1", True]
    assert pending.cost_micro_usd == pending.conservative_cost_micro_usd == 100
    assert pending.estimated_requests == 1
    uncertain = grouped["foundry", "model-1", False]
    assert uncertain.cost_micro_usd == uncertain.conservative_cost_micro_usd == 24
    assert uncertain.estimated_requests == 1
    assert grouped["language", "sentiment", False].cost_micro_usd == 2000


async def test_callers_endpoint_enforces_identity_and_labels_are_admin_only_configuration(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
) -> None:
    identities = [
        ("tenant-1", "user-1", "app-1"),
        ("tenant-1", "other-user", "app-1"),
        ("tenant-1", "user-1", "other-app"),
        ("other-tenant", "user-1", "app-3"),
    ]
    for index, (tenant, principal, subscription) in enumerate(identities):
        await engine.reserve(
            request_body.model_copy(
                update={
                    "tenant_id": tenant,
                    "principal_id": principal,
                    "subscription_id": subscription,
                    "request_id": f"caller-{index}",
                }
            )
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)), base_url="http://test"
    ) as client:
        label = {
            "id": "label",
            "tenant_id": "tenant-1",
            "subscription_id": "app-1",
            "policy_ids": ["policy-1"],
            "reader_principal_ids": ["user-1"],
            "display_label": "Research application",
        }
        assert (
            await client.put("/api/assignments/label", headers=READER, json=label)
        ).status_code == 403
        assert (
            await client.put("/api/assignments/label", headers=ADMIN, json=label)
        ).status_code == 200
        assert (await client.get("/api/usage/callers")).status_code == 401
        assert (await client.get("/api/usage/callers", headers=GATEWAY)).status_code == 403
        own = (
            await client.get(
                "/api/usage/callers?period=hour&tenant_id=other-tenant&principal_id=other-user",
                headers=READER,
            )
        ).json()
        assert len(own) == 1
        assert (own[0]["tenant_id"], own[0]["subscription_id"]) == identities[0][::2]
        assert own[0]["display_label"] == "Research application"
        assert own[0]["request_count"] == 2
        assert own[0]["caller_ref"] == caller_ref("tenant-1", "app-1")
        all_rows = (await client.get("/api/usage/callers", headers=ADMIN)).json()
        assert len(all_rows) == len({row["caller_ref"] for row in all_rows}) == 3
        assert [row["display_label"] for row in all_rows].count(None) == 2
        assert (
            await client.get("/api/usage/callers?period=month", headers=READER)
        ).status_code == 422
        assert len((await client.get("/api/usage", headers=READER)).json()) == 2
        assert (
            await client.get(
                "/api/usage/callers", headers={**READER, "X-Local-Principal-Id": "absent"}
            )
        ).json() == []
        assert (
            await client.put(
                "/api/assignments/label", headers=ADMIN, json={**label, "display_label": None}
            )
        ).status_code == 200
        assert (await client.get("/api/usage/callers", headers=READER)).json()[0][
            "display_label"
        ] is None
