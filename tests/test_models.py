from decimal import Decimal

import httpx
import pytest

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment

ADMIN = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "admin",
    "X-Local-Roles": "RateLimit.Admin",
}


async def configure_models(
    engine: Engine, registry: dict[str, ModelDeployment], budget: int = 100_000
) -> None:
    engine.settings.model_registry = registry
    for key in registry:
        alias = key.partition(":")[2]
        multiplier = Decimal(2 if alias.endswith("premium") else 1)
        price = Price(
            id=alias,
            service="foundry",
            model=alias,
            version="v1",
            input_per_million=2 * multiplier,
            output_per_million=4 * multiplier,
            cached_input_per_million=multiplier / 2,
            cache_write_5m_per_million=Decimal("2.5") * multiplier,
            cache_write_1h_per_million=4 * multiplier,
            per_request="0",
        )
        await engine.repository.create("prices", alias, price.model_dump(mode="json"))
    await engine.repository.mutate(
        "policies",
        "policy-1",
        Policy(
            id="policy-1",
            name="All model budget",
            service="foundry",
            subscription_id="*",
            limit=budget,
            period="day",
            metric="cost",
        ).model_dump(mode="json"),
        {"id": "configure-models"},
    )


async def test_two_models_of_each_protocol_use_their_own_pinned_prices(
    engine: Engine, request_body: Reserve, model_registry: dict[str, ModelDeployment]
) -> None:
    await configure_models(engine, model_registry)
    for key, deployment in model_registry.items():
        protocol, _, alias = key.partition(":")
        decision = await engine.reserve(
            request_body.model_copy(
                update={"request_id": alias, "model": alias, "api_protocol": protocol}
            )
        )
        assert decision.allowed
        intent = await engine.repository.get("intents", decision.reservation_id)
        assert intent["data"]["request"]["price_version"] == deployment.price_version
        if protocol == "openai-chat":
            raw = {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 8},
            }
        elif protocol == "openai-responses":
            raw = {
                "input_tokens": 10,
                "output_tokens": 5,
                "input_tokens_details": {"cached_tokens": 8},
            }
        else:
            raw = {
                "input_tokens": 2,
                "cache_read_input_tokens": 8,
                "cache_creation_input_tokens": 0,
                "output_tokens": 5,
            }
        result = await engine.settle(
            Settle(reservation_id=decision.reservation_id, status="actual", provider_usage=raw)
        )
        assert result["data"]["cost_micro_usd"] == (56 if alias.endswith("premium") else 28)
        assert not result["data"]["estimated"]
    assert list(engine.counters.counts.values()) == [252]


async def test_model_specific_and_shared_budgets_apply_together(
    engine: Engine, request_body: Reserve, model_registry: dict[str, ModelDeployment]
) -> None:
    await configure_models(engine, model_registry, budget=320)
    policy = Policy(
        id="premium-only",
        name="Premium model budget",
        service="foundry",
        subscription_id="*",
        model="chat-premium",
        limit=200,
        period="day",
        metric="cost",
    )
    await engine.repository.create("policies", policy.id, policy.model_dump(mode="json"))
    fast = await engine.reserve(
        request_body.model_copy(update={"request_id": "fast", "model": "chat-fast"})
    )
    premium = await engine.reserve(
        request_body.model_copy(update={"request_id": "premium", "model": "chat-premium"})
    )
    assert fast.allowed and premium.allowed
    assert sorted(engine.counters.counts.values()) == [200, 300]
    denied = await engine.reserve(
        request_body.model_copy(update={"request_id": "blocked", "model": "chat-fast"})
    )
    assert not denied.allowed and denied.denied_policy_ids == ["policy-1"]
    await engine.settle(
        Settle(
            reservation_id=fast.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
        )
    )
    assert (
        await engine.reserve(
            request_body.model_copy(update={"request_id": "after-refund", "model": "chat-fast"})
        )
    ).allowed
    assert sorted(engine.counters.counts.values()) == [200, 318]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model": "not-registered"}, "Unknown model alias"),
        ({"model": "chat-fast", "api_protocol": "openai-responses"}, "incompatible"),
        ({"model": "chat-fast", "price_version": "v2"}, "Price version"),
        ({"model": "chat-fast", "usage": Usage(input_tokens=101, output_tokens=1)}, "bounds"),
        ({"model": "chat-fast", "usage": Usage(input_tokens=1, output_tokens=21)}, "bounds"),
    ],
)
async def test_invalid_model_selections_fail_before_reserving(
    engine: Engine,
    request_body: Reserve,
    model_registry: dict[str, ModelDeployment],
    changes: dict,
    message: str,
) -> None:
    await configure_models(engine, model_registry)
    with pytest.raises(ValueError, match=message):
        await engine.reserve(request_body.model_copy(update=changes))
    assert await engine.repository.list("intents") == []
    assert not engine.counters.counts


async def test_catalog_changes_do_not_reprice_registered_inflight_requests(
    engine: Engine, request_body: Reserve, model_registry: dict[str, ModelDeployment]
) -> None:
    await configure_models(engine, model_registry)
    request = request_body.model_copy(update={"model": "chat-fast"})
    decision = await engine.reserve(request)
    engine.settings.model_registry["openai-chat:chat-fast"] = model_registry[
        "openai-chat:chat-fast"
    ].model_copy(update={"price_version": "v2"})
    assert (await engine.reserve(request)).reservation_id == decision.reservation_id
    old = await engine.repository.get("prices", "chat-fast")
    await engine.repository.mutate(
        "prices", "chat-fast", {**old, "version": "v2", "input_per_million": "100"}, {"id": "new"}
    )
    result = await engine.settle(
        Settle(
            reservation_id=decision.reservation_id,
            status="actual",
            usage=Usage(input_tokens=8, output_tokens=2, cached_input_tokens=4),
        )
    )
    assert result["data"]["cost_micro_usd"] == 18
    after = await engine.reserve(request.model_copy(update={"request_id": "after-catalog-change"}))
    after_intent = await engine.repository.get("intents", after.reservation_id)
    assert after_intent["data"]["request"]["price_version"] == "v2"


async def test_model_discovery_is_authorized_read_only_and_hides_backend_destinations(
    engine: Engine, settings: Settings, model_registry: dict[str, ModelDeployment]
) -> None:
    settings.model_registry = model_registry
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)), base_url="http://test"
    ) as client:
        assert (await client.get("/api/models")).status_code == 401
        assert (
            await client.get("/api/models", headers={**ADMIN, "X-Local-Roles": "RateLimit.Gateway"})
        ).status_code == 403
        for headers in (
            {**ADMIN, "X-Local-Roles": "RateLimit.Admin"},
            {
                **ADMIN,
                "X-Local-Principal-Id": "user-1",
                "X-Local-Roles": "RateLimit.Reader",
            },
        ):
            response = await client.get("/api/models", headers=headers)
            assert response.status_code == 200 and len(response.json()) == 6
            assert response.json()[0]["model"] != response.json()[0]["deployment_name"]
            assert set(response.json()[0]) == {
                "id",
                "model",
                "api_protocol",
                "deployment_name",
                "price_version",
                "max_input_tokens",
                "max_output_tokens",
            }
            assert "https://" not in response.text
        assert (await client.post("/api/models", headers=ADMIN, json={})).status_code == 405


async def test_empty_legacy_registry_is_discoverable(engine: Engine, settings: Settings) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)), base_url="http://test"
    ) as client:
        assert (await client.get("/api/models", headers=ADMIN)).json() == []
