from azure.data.tables.aio import TableClient
from azure.identity.aio import DefaultAzureCredential

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.credential: DefaultAzureCredential | None = None
        if settings.local_store_enabled:
            self.engine = Engine(MemoryRepository(), MemoryCounters(), settings)
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
                credential=self.credential,
                audience=(
                    "https://storage.azure.us"
                    if settings.azure_cloud == "government"
                    else "https://storage.azure.com"
                ),
            )
            self.engine = Engine(
                TableRepository(table), RedisCounters(settings, self.credential), settings
            )

    async def close(self) -> None:
        await self.engine.repository.close()
        await self.engine.counters.close()
        if self.credential:
            await self.credential.close()
