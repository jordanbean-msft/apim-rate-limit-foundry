import base64
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apim_rate_limit_foundry.auth import Identity, authenticate
from apim_rate_limit_foundry.config import Settings
from tests.test_auth import azure_settings


def principal_request(principal: object) -> Request:
    encoded = base64.b64encode(json.dumps(principal).encode())
    return Request({"type": "http", "headers": [(b"x-ms-client-principal", encoded)]})


def claims(*pairs: tuple[str, str]) -> dict:
    return {"auth_typ": "aad", "claims": [{"typ": name, "val": value} for name, value in pairs]}


IDENTITY = (("tid", "tenant-id"), ("oid", "user-object-id"))


@pytest.mark.parametrize(
    "principal",
    [
        ["not", "an", "object"],
        {**claims(*IDENTITY), "auth_typ": "google"},
        {"auth_typ": "aad"},
        {"auth_typ": "aad", "claims": "tid=tenant"},
        {"auth_typ": "aad", "claims": [{"typ": "tid", "val": 7}, {"typ": "oid", "val": "o"}]},
        {"auth_typ": "aad", "claims": ["tid"]},
        claims(("tid", "tenant-id")),
        claims(*IDENTITY, ("oid", "second-object-id")),
        claims(("tid", "tenant-a"), ("tid", "tenant-b"), ("oid", "user")),
    ],
)
def test_malformed_or_ambiguous_platform_principals_are_rejected(principal: object) -> None:
    with pytest.raises(HTTPException) as error:
        authenticate(principal_request(principal), azure_settings())

    assert error.value.status_code == 401


def test_undecodable_or_oversized_platform_principals_are_rejected() -> None:
    settings = azure_settings()
    garbage = Request({"type": "http", "headers": [(b"x-ms-client-principal", b"@@@")]})
    oversized = Request({"type": "http", "headers": [(b"x-ms-client-principal", b"A" * 70_000)]})
    missing = Request({"type": "http", "headers": []})

    for request in (garbage, oversized, missing):
        with pytest.raises(HTTPException) as error:
            authenticate(request, settings)
        assert error.value.status_code == 401


def test_mapped_claim_uris_and_roles_are_accepted() -> None:
    schema = "http://schemas.microsoft.com/identity/claims"
    request = principal_request(
        claims(
            (f"{schema}/tenantid", "tenant-id"),
            (f"{schema}/objectidentifier", "user-object-id"),
            ("http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "RateLimit.Reader"),
        )
    )

    identity = authenticate(request, azure_settings())

    assert identity == Identity("tenant-id", "user-object-id", frozenset({"RateLimit.Reader"}))


def test_the_configured_tenant_is_enforced() -> None:
    settings = azure_settings()
    settings.azure_tenant_id = "expected-tenant"

    with pytest.raises(HTTPException, match="Invalid tenant"):
        authenticate(principal_request(claims(*IDENTITY)), settings)


def test_authentication_must_be_configured() -> None:
    request = Request({"type": "http", "headers": []})

    with pytest.raises(HTTPException) as error:
        authenticate(request, Settings(_env_file=None))

    assert (error.value.status_code, error.value.detail) == (
        401,
        "Authentication is not configured",
    )


def test_local_headers_require_a_tenant_and_principal(settings: Settings) -> None:
    request = Request({"type": "http", "headers": [(b"x-local-tenant-id", b"tenant-1")]})

    with pytest.raises(HTTPException, match="Invalid tenant or principal"):
        authenticate(request, settings)


def test_roles_must_match_to_authorize() -> None:
    identity = Identity("tenant", "user", frozenset({"RateLimit.Reader"}))

    identity.require("RateLimit.Reader", "RateLimit.Admin")
    with pytest.raises(HTTPException) as error:
        identity.require("RateLimit.Admin")
    assert error.value.status_code == 403
