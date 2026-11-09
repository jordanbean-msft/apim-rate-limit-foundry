import pytest
from pydantic import ValidationError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment


def deployment(protocol: str = "openai-chat") -> ModelDeployment:
    model = "gpt-deployment"
    return ModelDeployment(
        api_protocol=protocol,
        endpoint="https://models.example.com",
        path=(
            f"/openai/deployments/{model}/chat/completions"
            if protocol == "openai-chat"
            else "/openai/v1/responses"
        ),
        model=model,
        audience="https://cognitiveservices.azure.com",
        api_version="2025-01-01-preview" if protocol == "openai-chat" else "",
        price_version="v1",
        max_input_tokens=100,
        max_output_tokens=20,
    )


@pytest.mark.parametrize("hostname", ["localhost:17071", "127.0.0.1:17071"])
def test_core_tools_loopback_allows_explicit_local_mode(
    monkeypatch: pytest.MonkeyPatch, hostname: str
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", hostname)
    settings = Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)
    assert not settings.in_azure


@pytest.mark.parametrize("marker", ["WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID"])
def test_real_azure_markers_prohibit_local_bypass(
    monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", "localhost:17071")
    monkeypatch.setenv(marker, "azure-site")
    with pytest.raises(ValueError, match="prohibited"):
        Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)


def test_registry_resolves_protocol_alias_and_enforces_fixed_paths() -> None:
    registry = {
        "openai-chat:fast": deployment("openai-chat"),
        "openai-responses:fast": deployment("openai-responses"),
    }
    settings = Settings(_env_file=None, model_registry=registry)
    assert settings.registered_model("openai-chat", "fast").api_version
    assert settings.registered_model("openai-responses", "fast").api_version == ""
    with pytest.raises(ValueError, match="Unknown"):
        settings.registered_model("openai-chat", "missing")

    entry = registry["openai-chat:fast"].model_dump()
    with pytest.raises(ValidationError, match="anthropic_version"):
        ModelDeployment.model_validate({**entry, "anthropic_version": "2023-06-01"})
    with pytest.raises(ValidationError, match="path must match"):
        ModelDeployment.model_validate({**entry, "path": "/arbitrary"})


def test_registry_rejects_malformed_protocol_keys_and_oversized_limits() -> None:
    with pytest.raises(ValueError, match="protocol:alias"):
        Settings(_env_file=None, model_registry={"bad": deployment()})
    with pytest.raises(ValueError, match="Function limits"):
        Settings(
            _env_file=None,
            model_registry={"openai-chat:fast": deployment()},
            max_input_tokens=99,
        )


def test_government_registry_requires_sovereign_origin_and_audience() -> None:
    government = deployment().model_dump()
    government.update(
        endpoint="https://models.openai.azure.us",
        audience="https://cognitiveservices.azure.us",
    )
    settings = Settings(
        _env_file=None,
        azure_cloud="government",
        model_registry={"openai-chat:fast": government},
    )
    assert settings.registered_model("openai-chat", "fast").endpoint.host.endswith(
        ".openai.azure.us"
    )
    with pytest.raises(ValueError, match="sovereign"):
        Settings(
            _env_file=None,
            azure_cloud="government",
            model_registry={
                "openai-chat:fast": {
                    **government,
                    "audience": "https://cognitiveservices.azure.com",
                }
            },
        )
