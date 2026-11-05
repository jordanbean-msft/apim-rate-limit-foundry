import pytest

from apim_rate_limit_foundry.config import Settings


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
