from unittest.mock import Mock

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.runtime import Runtime


def test_runtime_uses_function_identity_for_outbound_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        table_endpoint="https://table.example.net",
        redis_host="redis.example.net",
        redis_username="function-identity",
        azure_client_id="function-client-id",
        gateway_client_id="gateway-client-id",
    )
    credential = object()
    credential_factory = Mock(return_value=credential)
    monkeypatch.setattr(
        "apim_rate_limit_foundry.runtime.DefaultAzureCredential", credential_factory
    )
    monkeypatch.setattr("apim_rate_limit_foundry.runtime.TableClient", Mock(return_value=object()))
    monkeypatch.setattr(
        "apim_rate_limit_foundry.runtime.RedisCounters", Mock(return_value=object())
    )
    monkeypatch.setattr("apim_rate_limit_foundry.runtime.Engine", Mock())

    Runtime(settings)

    credential_factory.assert_called_once_with(
        authority=settings.authority,
        managed_identity_client_id="function-client-id",
        exclude_interactive_browser_credential=True,
    )
