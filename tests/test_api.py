import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Price, Reserve

ADMIN = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "admin",
    "X-Local-Roles": "RateLimit.Admin",
}
GATEWAY = {**ADMIN, "X-Local-Roles": "RateLimit.Gateway"}
READER = {**ADMIN, "X-Local-Principal-Id": "user-1", "X-Local-Roles": "RateLimit.Reader"}


async def test_crud_audit_consumer_scopes_and_gateway_role(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
) -> None:
    app = create_app(settings, engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/health")).json()["status"] == "ok"
        assert (await client.get("/api/policies")).status_code == 401
        assert (await client.get("/api/policies", headers=READER)).status_code == 200
        body = request_body.model_dump(mode="json")
        assert (
            await client.post("/api/decisions/reserve", json=body, headers=READER)
        ).status_code == 403
        response = await client.post("/api/decisions/reserve", json=body, headers=GATEWAY)
        assert response.status_code == 200 and response.json()["allowed"]
        record_id = response.json()["reservation_id"]
        result = await client.post(
            "/api/decisions/settle",
            headers=GATEWAY,
            json={
                "reservation_id": record_id,
                "status": "actual",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )
        assert result.status_code == 200
        assert len((await client.get("/api/usage", headers=READER)).json()) == 1
        other_tenant = {**READER, "X-Local-Tenant-Id": "another"}
        assert (await client.get("/api/usage", headers=other_tenant)).json() == []
        assert (await client.get("/api/reconciliation", headers=other_tenant)).json() == []
        assignment = {
            "id": "a",
            "tenant_id": "tenant-1",
            "principal_id": "user-1",
            "policy_ids": ["policy-1"],
        }
        assert (
            await client.put("/api/assignments/a", headers=READER, json=assignment)
        ).status_code == 403
        assert (
            await client.put("/api/assignments/a", headers=ADMIN, json=assignment)
        ).status_code == 200
        assert (
            await client.put("/api/assignments/wrong", headers=ADMIN, json=assignment)
        ).status_code == 400
        assert (
            await client.put(
                "/api/assignments/a", headers=ADMIN, json={**assignment, "unexpected": True}
            )
        ).status_code == 422
        assert (await client.get("/api/assignments", headers=READER)).json() == [assignment]
        assert (await client.get("/api/assignments", headers=other_tenant)).json() == []
        assert (await client.get("/api/policies", headers=other_tenant)).json() == []
        assert (await client.delete("/api/assignments/a", headers=ADMIN)).status_code == 200
        assert (await client.get("/api/assignments", headers=ADMIN)).json() == []
        history = (await client.get("/api/audit", headers=ADMIN)).json()
        assert len(history) == 2
        assert (
            next(row for row in history if row["data"]["action"] == "put")["data"]["record"]
            == assignment
        )
        assert (await client.get("/api/audit", headers=READER)).json() == []
        assert (await client.get("/api/not-real", headers=ADMIN)).status_code == 404
        assert (await client.post("/api/reconciliation/recover", headers=ADMIN)).status_code == 200


async def test_storage_and_invalid_estimate_errors_fail_closed(
    engine: Engine,
    settings: Settings,
    request_body: Reserve,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        engine.repository.fail = True
        assert (
            await client.post(
                "/api/decisions/reserve", headers=GATEWAY, json=request_body.model_dump(mode="json")
            )
        ).status_code == 503
        engine.repository.fail = False
        assert (
            await client.post(
                "/api/decisions/reserve",
                headers=GATEWAY,
                json={
                    **request_body.model_dump(mode="json"),
                    "usage": {"input_tokens": 0},
                },
            )
        ).status_code == 400


async def test_easy_auth_headers_not_trusted_on_local_host(engine: Engine) -> None:
    claims = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "tid", "val": "tenant-1"},
            {"typ": "oid", "val": "admin"},
            {"typ": "roles", "val": "RateLimit.Admin"},
        ],
    }
    forged = {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(claims).encode()).decode()}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Settings(_env_file=None), engine)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/policies", headers=forged)).status_code == 401


async def test_platform_claims_require_expected_tenant_and_role(engine: Engine) -> None:
    settings = Settings(
        _env_file=None,
        website_site_name="app",
        website_auth_enabled=True,
        azure_tenant_id="tenant-1",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        claims = {
            "auth_typ": "aad",
            "claims": [
                {"typ": "tid", "val": "tenant-1"},
                {"typ": "oid", "val": "admin"},
                {"typ": "roles", "val": "RateLimit.Admin"},
            ],
        }

        def encoded() -> dict[str, str]:
            return {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(claims).encode()).decode()}

        assert (await client.get("/api/policies", headers=encoded())).status_code == 200
        claims["claims"][0]["val"] = "wrong"
        assert (await client.get("/api/policies", headers=encoded())).status_code == 401
        claims["claims"][0]["val"] = "tenant-1"
        claims["claims"][2]["val"] = "not-a-role"
        assert (await client.get("/api/policies", headers=encoded())).status_code == 403
        assert (
            await client.get("/api/policies", headers={"X-MS-CLIENT-PRINCIPAL": "invalid"})
        ).status_code == 401


def test_local_bypass_prohibited_with_any_azure_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSITE_CUSTOM_PLATFORM_FLAG", "present")
    with pytest.raises(ValidationError, match="prohibited"):
        Settings(_env_file=None, local_auth_enabled=True)
    with pytest.raises(ValidationError, match="required"):
        Settings(_env_file=None)
    government = Settings(_env_file=None, website_auth_enabled=True, azure_cloud="government")
    assert government.authority == "https://login.microsoftonline.us"
    with pytest.raises(ValueError, match="explicitly verified"):
        _ = government.redis_scope
    government.redis_token_scope = "https://verified-resource.example/.default"
    assert government.redis_scope == "https://verified-resource.example/.default"


async def test_local_runtime_is_explicit(settings: Settings) -> None:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/api/prices", headers=ADMIN)).json() == []


async def test_catalog_overwrites_keep_both_typed_versions_in_audit(
    engine: Engine,
    settings: Settings,
    price: Price,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, engine)),
        base_url="http://test",
    ) as client:
        for version in ("v1", "v2"):
            record = {**price.model_dump(mode="json"), "version": version}
            response = await client.put(f"/api/prices/{price.id}", json=record, headers=ADMIN)
            assert response.status_code == 200
        catalog = (await client.get("/api/prices", headers=ADMIN)).json()
        history = (await client.get("/api/audit", headers=ADMIN)).json()
    assert catalog[0]["version"] == "v2"
    assert {row["data"]["record"]["version"] for row in history} == {"v1", "v2"}
