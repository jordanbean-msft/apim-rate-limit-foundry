import base64
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apim_rate_limit_foundry.auth import authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment


def gateway_request(*claims: tuple[str, str]) -> Request:
    principal = {
        "auth_typ": "aad",
        "claims": [{"typ": name, "val": value} for name, value in claims],
    }
    encoded = base64.b64encode(json.dumps(principal).encode())
    return Request({"type": "http", "headers": [(b"x-ms-client-principal", encoded)]})


def azure_settings() -> Settings:
    deployment = ModelDeployment(
        api_protocol="openai-chat",
        endpoint="https://models.example.com",
        path="/openai/deployments/model/chat/completions",
        model="model",
        audience="https://cognitiveservices.azure.com",
        api_version="2025-01-01-preview",
        price_version="v1",
        max_input_tokens=100,
        max_output_tokens=20,
    )
    return Settings(
        _env_file=None,
        website_site_name="rate-limiter",
        website_auth_enabled=True,
        gateway_client_id="gateway-client-id",
        model_registry={"openai-chat:model": deployment},
    )


def test_gateway_role_requires_configured_client_identity() -> None:
    settings = azure_settings()
    identity = authenticate(
        gateway_request(
            ("tid", "tenant-id"),
            ("oid", "gateway-object-id"),
            ("roles", "RateLimit.Gateway"),
            ("azp", "gateway-client-id"),
        ),
        settings,
    )
    assert identity.principal_id == "gateway-object-id"
    assert "RateLimit.Gateway" in identity.roles


@pytest.mark.parametrize(
    "client_claims",
    [
        (),
        (("azp", "other-client-id"),),
        (("appid", "other-client-id"),),
        (("azp", "gateway-client-id"), ("appid", "other-client-id")),
    ],
)
def test_gateway_role_rejects_missing_or_mismatched_client_identity(
    client_claims: tuple[tuple[str, str], ...],
) -> None:
    settings = azure_settings()
    with pytest.raises(HTTPException) as error:
        authenticate(
            gateway_request(
                ("tid", "tenant-id"),
                ("oid", "gateway-object-id"),
                ("roles", "RateLimit.Gateway"),
                *client_claims,
            ),
            settings,
        )
    assert error.value.status_code == 401
