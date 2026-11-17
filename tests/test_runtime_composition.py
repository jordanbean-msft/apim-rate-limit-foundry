import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from apim_rate_limit_foundry.stores.table import TableRepository
from tests.test_settings_validation import DASHBOARD, UUID, WORKSPACE


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    table = Mock(close=AsyncMock())
    redis = Mock(close=AsyncMock())
    dashboard = Mock(close=AsyncMock())
    credential = Mock(close=AsyncMock())
    created = SimpleNamespace(
        table=table,
        redis=redis,
        dashboard=dashboard,
        credential=credential,
        table_client=Mock(return_value=table, **{"from_connection_string.return_value": table}),
        redis_counters=Mock(return_value=redis, **{"from_url.return_value": redis}),
        dashboard_service=Mock(return_value=dashboard),
        credential_factory=Mock(return_value=credential),
    )
    prefix = "apim_rate_limit_foundry.runtime."
    monkeypatch.setattr(prefix + "TableClient", created.table_client)
    monkeypatch.setattr(prefix + "RedisCounters", created.redis_counters)
    monkeypatch.setattr(prefix + "DashboardService", created.dashboard_service)
    monkeypatch.setattr(prefix + "DefaultAzureCredential", created.credential_factory)
    return created


def cloud(**changes: object) -> Settings:
    values: dict[str, object] = {
        "table_endpoint": "https://table.example.net",
        "redis_host": "redis.example.net",
        "redis_username": "function-identity",
    }
    return Settings(_env_file=None, **{**values, **changes})


def test_local_mode_defaults_to_memory_stores(settings: Settings) -> None:
    runtime = Runtime(settings)

    assert isinstance(runtime.gateway.repository, MemoryRepository)
    assert isinstance(runtime.gateway.counters, MemoryCounters)
    assert runtime.credential is None and runtime.dashboard is None


def test_local_mode_uses_emulators_only_when_both_endpoints_are_configured(
    clients: SimpleNamespace,
) -> None:
    settings = Settings(
        _env_file=None,
        local_store_enabled=True,
        local_redis_url="redis://localhost:6379",
        local_table_connection_string=SecretStr("UseDevelopmentStorage=true"),
    )

    runtime = Runtime(settings)

    clients.table_client.from_connection_string.assert_called_once_with(
        conn_str="UseDevelopmentStorage=true", table_name=settings.table_name
    )
    clients.redis_counters.from_url.assert_called_once_with(settings, "redis://localhost:6379")
    assert isinstance(runtime.gateway.repository, TableRepository)
    assert runtime.gateway.counters is clients.redis


@pytest.mark.parametrize("missing", ["table_endpoint", "redis_host", "redis_username"])
def test_cloud_mode_requires_every_dependency_and_never_falls_back_to_memory(
    clients: SimpleNamespace, missing: str
) -> None:
    with pytest.raises(ValueError, match="TABLE_ENDPOINT, REDIS_HOST and REDIS_USERNAME"):
        Runtime(cloud(**{missing: ""}))

    clients.credential_factory.assert_not_called()


@pytest.mark.parametrize(
    ("changes", "audience"),
    [
        ({}, "https://storage.azure.com"),
        (
            {"azure_cloud": "government", "redis_token_scope": "https://redis.example/.default"},
            "https://storage.azure.us",
        ),
    ],
)
def test_cloud_table_audience_follows_the_azure_cloud(
    clients: SimpleNamespace, changes: dict, audience: str
) -> None:
    Runtime(cloud(**changes))

    assert clients.table_client.call_args.kwargs["audience"] == audience


async def test_dashboard_is_created_only_with_dashboard_settings_and_everything_closes(
    clients: SimpleNamespace,
) -> None:
    runtime = Runtime(
        cloud(
            azure_dashboard_id=DASHBOARD,
            log_analytics_workspace_id=UUID,
            log_analytics_workspace_resource_id=WORKSPACE,
        )
    )
    session = runtime.http_session()

    await runtime.close()

    assert runtime.dashboard is clients.dashboard
    for closed in (clients.table, clients.redis, clients.dashboard, clients.credential):
        closed.close.assert_awaited_once()
    assert session.closed


def test_cloud_mode_without_dashboard_settings_has_no_dashboard(clients: SimpleNamespace) -> None:
    assert Runtime(cloud()).dashboard is None
    clients.dashboard_service.assert_not_called()


async def test_runtime_drains_and_closes_when_its_event_loop_cancels_remaining_tasks(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Runtime(settings)
    drain = AsyncMock()
    monkeypatch.setattr(runtime.gateway.background, "close", drain)
    runtime.close_on_loop_shutdown()
    guard = runtime._shutdown_guard
    runtime.close_on_loop_shutdown()
    assert runtime._shutdown_guard is guard

    assert guard is not None
    await asyncio.sleep(0)
    guard.cancel()
    with pytest.raises(asyncio.CancelledError):
        await guard

    drain.assert_awaited_once()


async def test_explicit_close_retires_the_shutdown_guard(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Runtime(settings)
    drain = AsyncMock()
    monkeypatch.setattr(runtime.gateway.background, "close", drain)
    runtime.close_on_loop_shutdown()
    guard = runtime._shutdown_guard

    await runtime.close()
    await asyncio.sleep(0)

    assert guard is not None and guard.cancelled()
    drain.assert_awaited_once()
