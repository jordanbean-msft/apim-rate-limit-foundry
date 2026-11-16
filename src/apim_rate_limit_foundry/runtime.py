"""Compose process-scoped clients while keeping cloud and local stores explicit."""

import aiohttp
from azure.data.tables.aio import TableClient
from azure.identity.aio import DefaultAzureCredential

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.reports.dashboard import DashboardService
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository


class Runtime:
    """Own the engine, shared credential, HTTP session and optional dashboard query clients."""

    def __init__(self, settings: Settings) -> None:
        """Select paired local stores or Entra-authenticated Azure dependencies.

        Local mode uses memory unless both emulator/persistent endpoints are
        configured. Cloud mode never silently falls back to local counters.
        """
        self.credential: DefaultAzureCredential | None = None
        self.dashboard: DashboardService | None = None
        self._http_session: aiohttp.ClientSession | None = None
        if settings.local_store_enabled:
            if settings.local_redis_url and settings.local_table_connection_string:
                table = TableClient.from_connection_string(
                    conn_str=settings.local_table_connection_string.get_secret_value(),
                    table_name=settings.table_name,
                )
                self.engine = Engine(
                    TableRepository(table),
                    RedisCounters.from_url(settings, settings.local_redis_url),
                    settings,
                )
            else:
                self.engine = Engine(MemoryRepository(), MemoryCounters(settings), settings)
        else:
            if (
                not settings.table_endpoint
                or not settings.redis_host
                or not settings.redis_username
            ):
                raise ValueError("TABLE_ENDPOINT, REDIS_HOST and REDIS_USERNAME are required")
            _ = settings.redis_scope
            self.credential = DefaultAzureCredential(
                authority=settings.authority,
                managed_identity_client_id=settings.azure_client_id,
                exclude_interactive_browser_credential=True,
            )
            table = TableClient(
                endpoint=settings.table_endpoint,
                table_name=settings.table_name,
                credential=ObservedCredential(self.credential),
                audience=(
                    "https://storage.azure.us"
                    if settings.azure_cloud == "government"
                    else "https://storage.azure.com"
                ),
            )
            self.engine = Engine(
                TableRepository(table), RedisCounters(settings, self.credential), settings
            )
            if settings.azure_dashboard_id:
                self.dashboard = DashboardService(settings, self.credential)

    def http_session(self) -> aiohttp.ClientSession:
        """Share one outbound HTTP session, created on first use inside the running loop.

        Callers set per-request timeouts; the session is closed with the runtime.
        """
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self) -> None:
        """Drain best-effort jobs before closing the clients those jobs still need.

        The writer's bounded drain is not a guarantee of persistence at shutdown.
        """
        await self.engine.background.close()
        if self.dashboard:
            await self.dashboard.close()
        await self.engine.repository.close()
        await self.engine.counters.close()
        if self._http_session:
            await self._http_session.close()
        if self.credential:
            await self.credential.close()
