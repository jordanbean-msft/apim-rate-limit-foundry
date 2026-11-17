import pytest
from pydantic import SecretStr, ValidationError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from tests.test_config import deployment

UUID = "00000000-0000-0000-0000-000000000001"
BASE = f"/subscriptions/{UUID}/resourceGroups/demo/providers"
WORKSPACE = f"{BASE}/Microsoft.OperationalInsights/workspaces/logs"
DASHBOARD = f"{BASE}/Microsoft.Portal/dashboards/dashboard"


def azure(**changes: object) -> Settings:
    values: dict[str, object] = {
        "website_site_name": "site",
        "website_auth_enabled": True,
        "model_registry": {"openai-chat:fast": deployment()},
    }
    return Settings(_env_file=None, **{**values, **changes})


def test_azure_requires_platform_auth_and_a_model_registry() -> None:
    with pytest.raises(ValueError, match="Easy Auth must be required"):
        azure(website_auth_enabled=False)
    with pytest.raises(ValueError, match="MODEL_REGISTRY is required"):
        azure(model_registry={})

    assert azure().in_azure


@pytest.mark.parametrize("local", [{"local_auth_enabled": True}, {"local_redis_url": "redis://x"}])
def test_azure_never_allows_local_bypasses(local: dict) -> None:
    with pytest.raises(ValueError, match="prohibited"):
        azure(**local)


def test_event_hub_namespace_and_name_come_as_a_pair() -> None:
    with pytest.raises(ValueError, match="EVENT_HUB_FQDN and EVENT_HUB_NAME"):
        Settings(_env_file=None, local_store_enabled=True, event_hub_fqdn="events.example")


def test_local_persistent_endpoints_come_as_a_pair_in_explicit_local_mode() -> None:
    connection = SecretStr("UseDevelopmentStorage=true")

    with pytest.raises(ValueError, match="required together"):
        Settings(_env_file=None, local_store_enabled=True, local_redis_url="redis://localhost")
    with pytest.raises(ValueError, match="required together"):
        Settings(_env_file=None, local_store_enabled=True, local_table_connection_string=connection)
    with pytest.raises(ValueError, match="LOCAL_STORE_ENABLED"):
        Settings(
            _env_file=None,
            local_redis_url="redis://localhost",
            local_table_connection_string=connection,
        )
    paired = Settings(
        _env_file=None,
        local_store_enabled=True,
        local_redis_url="redis://localhost",
        local_table_connection_string=connection,
    )
    assert paired.local_redis_url == "redis://localhost"


def dashboard(**changes: str) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "azure_dashboard_id": DASHBOARD,
            "log_analytics_workspace_id": UUID,
            "log_analytics_workspace_resource_id": WORKSPACE,
            **changes,
        },
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"log_analytics_workspace_id": ""}, "configured together"),
        ({"azure_dashboard_id": "/subscriptions/x/dashboards/d"}, "fixed Azure resource IDs"),
        ({"log_analytics_workspace_resource_id": WORKSPACE + "/../x"}, "fixed Azure resource IDs"),
        ({"log_analytics_workspace_id": "not-a-guid"}, "customer ID must be a UUID"),
    ],
)
def test_dashboard_settings_must_name_fixed_resources(changes: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dashboard(**changes)

    assert dashboard().azure_dashboard_id == DASHBOARD


def test_redis_scope_defaults_to_the_commercial_cloud_and_is_explicit_elsewhere() -> None:
    assert Settings(_env_file=None).redis_scope == "https://redis.azure.com/.default"
    assert Settings(_env_file=None, redis_token_scope="custom/.default").redis_scope == (
        "custom/.default"
    )
    with pytest.raises(ValueError, match="explicitly verified"):
        Settings(_env_file=None, azure_cloud="government").redis_scope  # noqa: B018


def test_government_endpoints_differ_from_commercial() -> None:
    commercial, government = (
        Settings(_env_file=None),
        Settings(_env_file=None, azure_cloud="government"),
    )

    assert "microsoftonline.com" in commercial.authority
    assert "microsoftonline.us" in government.authority
    assert government.management_endpoint.endswith("usgovcloudapi.net")
    assert government.logs_endpoint.endswith("loganalytics.us")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"endpoint": "http://models.example.com"}, "fixed HTTPS origins"),
        ({"audience": "https://user:pw@cognitiveservices.azure.com"}, "fixed HTTPS origins"),
        ({"endpoint": "https://models.example.com/openai"}, "must not contain paths"),
        ({"audience": "https://cognitiveservices.azure.com/tenant"}, "must not contain paths"),
        ({"api_version": "2025 01"}, "safe identifier"),
    ],
)
def test_model_backends_reject_unsafe_origins_and_versions(changes: dict, message: str) -> None:
    entry = deployment().model_dump(mode="json")

    with pytest.raises(ValidationError, match=message):
        ModelDeployment.model_validate({**entry, **changes})
