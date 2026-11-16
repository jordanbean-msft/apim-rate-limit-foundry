import httpx

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine

ADMIN = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "admin",
    "X-Local-Roles": "RateLimit.Admin",
}
GATEWAY = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "gateway",
    "X-Local-Roles": "RateLimit.Gateway",
}
READER = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "user-1",
    "X-Local-Roles": "RateLimit.Reader",
}


async def test_budget_api_records_usage_and_serves_scoped_chargeback(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    body = {
        "request_id": "api-request",
        "tenant_id": "tenant-1",
        "principal_id": "user-1",
        "subscription_id": "apim-app",
        "model": "model-1",
        "api_protocol": "openai-chat",
        "streaming": False,
    }
    usage_body = {
        "request_id": "api-request",
        "status": "actual",
        "provider_usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/budgets", headers=GATEWAY)).status_code == 403
        assert (
            await client.post("/api/budgets/check", json=body, headers=ADMIN)
        ).status_code == 403
        admitted = await client.post("/api/budgets/check", json=body, headers=GATEWAY)
        assert admitted.status_code == 200 and admitted.json()["allowed"]
        recorded = await client.post("/api/usage/record", json=usage_body, headers=GATEWAY)
        assert recorded.status_code == 200
        assert recorded.json()["event"]["cost_micro_usd"] == 100
        replay = await client.post("/api/usage/record", json=usage_body, headers=GATEWAY)
        assert replay.json()["replayed"] is True
        await engine.background.flush()

        own_usage = await client.get("/api/usage", headers=READER)
        assert len(own_usage.json()) == 1
        status = await client.get("/api/budgets/status", headers=READER)
        assert len(status.json()) == 3
        assert all(item["spent_micro_usd"] == 100 for item in status.json())
        month = recorded.json()["event"]["month"]
        chargeback = await client.get(f"/api/chargeback?month={month}&format=json", headers=READER)
        assert chargeback.status_code == 200
        assert chargeback.json()[0]["cost_micro_usd"] == 100
        csv_export = await client.get(f"/api/chargeback?month={month}&format=csv", headers=ADMIN)
        assert csv_export.status_code == 200
        assert "business_unit,cost_center" in csv_export.text


async def test_unknown_usage_is_visible_and_charged_the_upper_bound(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {
            "request_id": "unknown-stream",
            "tenant_id": "tenant-1",
            "principal_id": "user-1",
            "subscription_id": "apim-app",
            "model": "model-1",
            "api_protocol": "openai-responses",
            "streaming": True,
        }
        assert (await client.post("/api/budgets/check", json=body, headers=GATEWAY)).json()[
            "allowed"
        ]
        result = await client.post(
            "/api/usage/record",
            json={
                "request_id": "unknown-stream",
                "status": "actual",
                "provider_usage": {"input_tokens": "bad", "output_tokens": 1},
            },
            headers=GATEWAY,
        )
        event = result.json()["event"]
        assert event["status"] == "usage_unknown"
        assert event["cost_basis"] == "estimated_upper_bound"
        assert event["cost_micro_usd"] == 131072 * 2 + 32768 * 4
        await engine.background.flush()
        rows = await client.get(f"/api/chargeback?month={event['month']}", headers=ADMIN)
        assert rows.json()[0]["unknown_requests"] == 1
        assert rows.json()[0]["cost_micro_usd"] == event["cost_micro_usd"]
        assert rows.json()[0]["input_tokens"] is None


async def test_config_crud_hierarchy_validation_and_removed_routes(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/organizations")).status_code == 401
        listing = await client.get("/api/organizations", headers=ADMIN)
        assert listing.status_code == 200 and len(listing.json()) == 2
        invalid = {
            "id": "bad-team",
            "tenant_id": "tenant-1",
            "kind": "team",
            "name": "Bad Team",
            "department_id": "missing",
            "business_unit": "BU",
            "cost_center": "CC",
            "enabled": True,
        }
        response = await client.put("/api/organizations/bad-team", json=invalid, headers=ADMIN)
        assert response.status_code == 400
        assert (await client.get("/api/decisions/reserve", headers=ADMIN)).status_code in (404, 405)
        assert (await client.post("/api/reconciliation/recover", headers=ADMIN)).status_code in (
            404,
            405,
        )
        assert (await client.post("/api/counters/rebuild", headers=ADMIN)).status_code == 405


async def test_usage_month_parameter_is_validated_and_scopes_history(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/usage?month=2030-13", headers=ADMIN)).status_code == 400
        assert (await client.get("/api/usage?month=2000-01", headers=ADMIN)).json() == []
        assert (await client.get("/api/usage?month=bad", headers=READER)).status_code == 400


async def test_models_listing_requires_an_assignment_for_readers(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    stranger = {**READER, "X-Local-Principal-Id": "stranger"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/models", headers=stranger)).json() == []
        assert (await client.get("/api/models", headers=READER)).status_code == 200


async def test_unknown_collections_are_not_found_for_every_verb(
    settings: Settings, engine: Engine
) -> None:
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/secrets", headers=ADMIN)).status_code == 404
        assert (await client.put("/api/secrets/x", json={}, headers=ADMIN)).status_code == 404
        assert (await client.delete("/api/secrets/x", headers=ADMIN)).status_code == 404
        for collection in ("budgets", "organizations", "assignments", "prices"):
            assert (await client.get(f"/api/{collection}", headers=ADMIN)).status_code == 200


async def test_invalid_stored_configuration_is_reported_without_its_contents(
    settings: Settings, engine: Engine
) -> None:
    budget = await engine.repository.get("budgets", "budget-team")
    assert budget is not None
    await engine.repository.mutate(
        "budgets", "budget-team", {**budget, "limit_micro_usd": "secret-value"}, {"id": "audit"}
    )
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/budgets", headers=ADMIN)
    assert response.status_code == 400
    assert "budget-team" in response.text and "secret-value" not in response.text
