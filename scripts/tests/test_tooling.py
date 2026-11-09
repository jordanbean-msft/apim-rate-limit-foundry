import json
import sys
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from scripts import configure_ci, seed
from scripts.archive_legacy_config import archive


def test_seed_dry_run_never_writes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["seed"])
    monkeypatch.setenv("SEED_API_URL", "http://127.0.0.1:8000/api")
    monkeypatch.setenv("SEED_LOCAL_AUTH", "false")
    client = MagicMock()
    monkeypatch.setattr(seed.httpx, "Client", Mock(return_value=client))

    seed.main()

    client.__enter__.return_value.put.assert_not_called()
    assert "Dry run only" in capsys.readouterr().out


def test_seed_apply_uses_access_token_and_real_collection_routes(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["seed", "--apply"])
    monkeypatch.setenv("SEED_API_URL", "https://gateway.example/api")
    monkeypatch.setenv("SEED_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("SEED_LOCAL_AUTH", "false")
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(respond)
    original_client = httpx.Client
    monkeypatch.setattr(
        seed.httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    seed.main()

    saved_price = json.loads(
        next(
            request for request in requests if request.url.path == "/api/prices/sample-model-v1"
        ).content
    )
    assert saved_price["cached_input_per_million"] == "0.20"
    assert {request.url.path.split("/")[2] for request in requests} == {
        "organizations",
        "assignments",
        "prices",
        "budgets",
    }
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    assert str(requests[0].url) == "https://gateway.example/api/organizations/engineering"


def test_archive_preserves_legacy_values_and_refuses_overwrite(tmp_path) -> None:
    source, destination = tmp_path / "source.json", tmp_path / "archive.json"
    original = {"usage": [{"id": "legacy", "cost": 123}]}
    source.write_text(json.dumps(original))

    archive(source, destination)

    assert json.loads(destination.read_text())["data"] == original
    assert json.loads(source.read_text()) == original
    assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        archive(source, destination)


def test_archive_rejects_non_collection_without_creating_output(tmp_path) -> None:
    source, destination = tmp_path / "source.json", tmp_path / "archive.json"
    source.write_text("null")

    with pytest.raises(ValueError, match="object or array"):
        archive(source, destination)

    assert not destination.exists()


def test_seed_cannot_send_local_admin_headers_to_cloud(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["seed", "--apply"])
    monkeypatch.setenv("SEED_API_URL", "https://gateway.example/api")
    monkeypatch.setenv("SEED_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("SEED_LOCAL_AUTH", "true")

    with pytest.raises(ValueError, match="loopback"):
        seed.main()


@pytest.mark.parametrize(
    "url",
    ["http://gateway.example/api", "https://user:password@gateway.example/api"],
)
def test_seed_rejects_unsafe_urls(monkeypatch, url: str) -> None:
    monkeypatch.setattr(sys, "argv", ["seed", "--apply"])
    monkeypatch.setenv("SEED_API_URL", url)

    with pytest.raises(ValueError):
        seed.main()


def test_ci_cloud_conflict_cannot_mutate_environment(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_ENV_NAME", "test")
    monkeypatch.setenv("AZURE_CLOUD", "AzureUSGovernment")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "test-subscription")
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("AZD_ENV_JSON", '{"AZURE_CLOUD": "AzureCloud"}')
    run = Mock()
    monkeypatch.setattr(configure_ci.subprocess, "run", run)

    with pytest.raises(ValueError, match="conflicts"):
        configure_ci.main()

    run.assert_not_called()


def test_ci_passes_values_without_shell_interpolation(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_ENV_NAME", "test")
    monkeypatch.setenv("AZURE_CLOUD", "AzureCloud")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "test-subscription")
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("AZD_ENV_JSON", '{"APIM_PUBLISHER_NAME":"Sample Publisher"}')
    run = Mock()
    monkeypatch.setattr(configure_ci.subprocess, "run", run)

    configure_ci.main()

    run.assert_any_call(
        ["azd", "env", "set", "APIM_PUBLISHER_NAME", "Sample Publisher"], check=True
    )
    assert all("shell" not in call.kwargs for call in run.call_args_list)
