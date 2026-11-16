from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.stores.contracts import Conflict

ADMIN = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "admin",
    "X-Local-Roles": "RateLimit.Admin",
}
READER = {**ADMIN, "X-Local-Principal-Id": "user-1", "X-Local-Roles": "RateLimit.Reader"}
TEAM = {
    "id": "team-2",
    "tenant_id": "tenant-1",
    "kind": "team",
    "name": "Data",
    "department_id": "department-1",
    "business_unit": "BU-ENG",
    "cost_center": "CC-100",
}


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


async def test_admin_configuration_is_saved_listed_and_deleted_through_the_api(
    settings: Settings, engine: Engine
) -> None:
    async with client_for(create_app(settings, engine)) as client:
        saved = await client.put("/api/organizations/team-2", json=TEAM, headers=ADMIN)
        listed = await client.get("/api/organizations", headers=ADMIN)
        deleted = await client.delete("/api/organizations/team-2", headers=ADMIN)
        relisted = await client.get("/api/organizations", headers=ADMIN)

    assert saved.status_code == 200 and saved.json()["id"] == "team-2"
    assert "team-2" in {row["id"] for row in listed.json()}
    assert deleted.json() == {"deleted": "team-2"}
    assert "team-2" not in {row["id"] for row in relisted.json()}


async def test_unknown_collections_are_not_found_and_non_admins_are_forbidden(
    settings: Settings, engine: Engine
) -> None:
    async with client_for(create_app(settings, engine)) as client:
        assert (await client.get("/api/secrets", headers=ADMIN)).status_code == 404
        assert (await client.put("/api/secrets/x", json={}, headers=ADMIN)).status_code == 404
        assert (await client.delete("/api/secrets/x", headers=ADMIN)).status_code == 404
        assert (
            await client.put("/api/organizations/x", json=TEAM, headers=READER)
        ).status_code == 403
        assert (await client.delete("/api/organizations/x", headers=READER)).status_code == 403


async def test_domain_errors_map_to_400_and_conflicts_to_409(
    settings: Settings, engine: Engine
) -> None:
    async with client_for(create_app(settings, engine)) as client:
        invalid = await client.put("/api/organizations/other-id", json=TEAM, headers=ADMIN)
        engine.save_configuration = AsyncMock(side_effect=Conflict("someone else owns this"))
        conflicting = await client.put("/api/organizations/team-2", json=TEAM, headers=ADMIN)

    assert invalid.status_code == 400 and "Path ID" in invalid.json()["detail"]
    assert conflicting.status_code == 409
    assert conflicting.json() == {"detail": "someone else owns this"}


@pytest.mark.parametrize("month", ["2030-13", "2030-1", "last-month", "2030-00"])
async def test_chargeback_rejects_malformed_months(
    settings: Settings, engine: Engine, month: str
) -> None:
    async with client_for(create_app(settings, engine)) as client:
        response = await client.get("/api/chargeback", params={"month": month}, headers=ADMIN)

    assert response.status_code == 400


async def test_dashboard_is_unavailable_when_telemetry_is_not_configured(
    settings: Settings, engine: Engine
) -> None:
    with patch("apim_rate_limit_foundry.api.Runtime", return_value=Mock(dashboard=None)):
        async with client_for(create_app(settings, engine)) as client:
            response = await client.get("/api/dashboard", headers=ADMIN)

    assert response.status_code == 503


async def test_cloud_clients_are_built_once_on_demand_and_closed_with_the_app(
    settings: Settings, engine: Engine
) -> None:
    runtime = Mock(engine=engine, close=AsyncMock())
    with patch("apim_rate_limit_foundry.api.Runtime", return_value=runtime) as build:
        app = create_app(settings)
        build.assert_not_called()
        async with app.router.lifespan_context(app):
            assert app.state.get_engine() is engine
            assert app.state.get_engine() is engine
        build.assert_called_once_with(settings)
    runtime.close.assert_awaited_once()


async def test_app_without_cloud_clients_shuts_down_cleanly(settings: Settings) -> None:
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        pass
