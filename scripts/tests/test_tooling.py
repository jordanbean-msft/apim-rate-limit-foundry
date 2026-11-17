import json
from unittest.mock import Mock

import pytest

from scripts import configure_ci
from scripts.archive_legacy_config import archive


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
