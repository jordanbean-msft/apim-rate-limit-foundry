import json

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment


@pytest.mark.parametrize("hostname", ["localhost:17071", "127.0.0.1:17071", "LOCALHOST:17071"])
def test_core_tools_loopback_hostname_allows_explicit_local_mode(
    monkeypatch: pytest.MonkeyPatch,
    hostname: str,
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", hostname)
    settings = Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)
    assert not settings.in_azure


@pytest.mark.parametrize("marker", ["WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID"])
def test_real_azure_markers_override_loopback_host_and_development_label(
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", "localhost:17071")
    monkeypatch.setenv(marker, "real-azure-marker")
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Development")
    with pytest.raises(ValueError, match="prohibited"):
        Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)


@pytest.mark.parametrize(
    "hostname",
    [
        "app.azurewebsites.net",
        "localhost.attacker:17071",
        "127.0.0.2:17071",
        "localhost",
        "127.0.0.1",
        "localhost:0",
        "localhost:65536",
        "localhost:17071/path",
    ],
)
def test_only_exact_loopback_with_valid_port_allows_local_mode(
    monkeypatch: pytest.MonkeyPatch,
    hostname: str,
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", hostname)
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Development")
    with pytest.raises(ValueError, match="prohibited"):
        Settings(_env_file=None, local_auth_enabled=True)


def test_registry_resolves_same_alias_independently_for_each_protocol(
    model_registry: dict[str, ModelDeployment],
) -> None:
    chat = model_registry["openai-chat:chat-fast"]
    responses = model_registry["openai-responses:responses-fast"]
    settings = Settings(
        _env_file=None,
        model_registry={"openai-chat:shared": chat, "openai-responses:shared": responses},
    )
    assert settings.registered_model("openai-chat", "shared").model == "chat-fast-deployment"
    assert (
        settings.registered_model("openai-responses", "shared").model == "responses-fast-deployment"
    )
    with pytest.raises(ValueError, match="Unknown"):
        settings.registered_model("anthropic-messages", "shared")


def test_application_registry_is_loaded_through_settings_and_validates_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "APPLICATION_REGISTRY",
        json.dumps(
            {
                "apim-app-1": {
                    "tenant_id": "tenant-1",
                    "display_name": "Research application",
                }
            }
        ),
    )
    settings = Settings(
        _env_file=None,
        local_auth_enabled=True,
        local_store_enabled=True,
    )
    assert settings.application_name("tenant-1", "apim-app-1") == "Research application"
    with pytest.raises(ValueError, match="Unknown application"):
        settings.application_name("tenant-2", "apim-app-1")
    with pytest.raises(ValueError, match="Unknown application"):
        settings.application_name("tenant-1", "unknown")
    monkeypatch.delenv("APPLICATION_REGISTRY")
    local = Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)
    assert local.application_name("tenant-1", "local-app") == "local-app"
    with pytest.raises(ValueError, match="APPLICATION_REGISTRY"):
        Settings(_env_file=None).application_name("tenant-1", "missing")


@pytest.mark.parametrize("key", ["chat-fast", "openai-chat:*", "openai-chat:bad/alias"])
def test_registry_rejects_malformed_keys(
    model_registry: dict[str, ModelDeployment], key: str
) -> None:
    with pytest.raises(ValueError, match="protocol:alias"):
        Settings(_env_file=None, model_registry={key: model_registry["openai-chat:chat-fast"]})


def test_registry_requires_consistent_protocol_and_function_limits(
    model_registry: dict[str, ModelDeployment],
) -> None:
    with pytest.raises(ValueError, match="protocol:alias"):
        Settings(
            _env_file=None,
            model_registry={"openai-responses:chat-fast": model_registry["openai-chat:chat-fast"]},
        )
    with pytest.raises(ValueError, match="Function limits"):
        Settings(_env_file=None, model_registry=model_registry, max_input_tokens=99)
    with pytest.raises(ValueError, match="Function limits"):
        Settings(_env_file=None, model_registry=model_registry, max_output_tokens=19)
    with pytest.raises(ValueError, match="Anthropic models"):
        Settings(
            _env_file=None,
            model_registry={
                "anthropic-messages:claude-fast": model_registry["anthropic-messages:claude-fast"]
            },
            azure_cloud="government",
        )


def test_registry_rejects_unpinned_protocol_paths_and_unsafe_destinations(
    model_registry: dict[str, ModelDeployment],
) -> None:
    entry = model_registry["openai-chat:chat-fast"].model_dump()
    with pytest.raises(ValueError, match="path must match"):
        ModelDeployment.model_validate({**entry, "path": "/arbitrary"})
    with pytest.raises(ValueError, match="must not contain paths"):
        ModelDeployment.model_validate({**entry, "endpoint": "https://models.example.com/path"})


def test_government_registry_cannot_use_commercial_model_endpoints_or_audiences(
    model_registry: dict[str, ModelDeployment],
) -> None:
    entry = model_registry["openai-chat:chat-fast"].model_dump()
    sovereign = {
        **entry,
        "endpoint": "https://models.openai.azure.us",
        "audience": "https://cognitiveservices.azure.us",
    }
    key = "openai-chat:chat-fast"
    settings = Settings(_env_file=None, azure_cloud="government", model_registry={key: sovereign})
    assert settings.registered_model("openai-chat", "chat-fast").endpoint.host.endswith(
        ".openai.azure.us"
    )
    for changed in (
        {"endpoint": "https://models.openai.azure.com"},
        {"audience": "https://cognitiveservices.azure.com"},
    ):
        with pytest.raises(ValueError, match="Government models require sovereign"):
            Settings(
                _env_file=None,
                azure_cloud="government",
                model_registry={key: {**sovereign, **changed}},
            )
