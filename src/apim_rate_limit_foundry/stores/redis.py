import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from azure.identity.aio import DefaultAzureCredential
from redis.asyncio import Redis
from redis.exceptions import RedisError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.contracts import Record
from apim_rate_limit_foundry.stores.scripts import REPLACE_PROJECTION
from apim_rate_limit_foundry.telemetry import emit, observe_dependency


class RedisCounters:
    """Redis serializes ledger reads and stores a rebuildable projection only."""

    projection_key = "{limiter}:usage-projection"
    lock_key = "{limiter}:usage-ledger-lock"

    def __init__(
        self,
        settings: Settings,
        credential: DefaultAzureCredential | None,
        client: Redis | None = None,
    ) -> None:
        self.settings = settings
        self.credential = credential
        self.client = client
        self.static_client = client is not None
        self.expires = 0
        self.connection_lock = asyncio.Lock()

    @classmethod
    def from_url(cls, settings: Settings, url: str) -> "RedisCounters":
        if not settings.local_store_enabled or settings.in_azure:
            raise ValueError("Redis URLs are only permitted in explicit local store mode")
        return cls(
            settings,
            None,
            Redis.from_url(
                url, decode_responses=True, socket_timeout=10, socket_connect_timeout=10
            ),
        )

    async def connection(self) -> Redis:
        async with self.connection_lock:
            if self.static_client:
                assert self.client is not None
                return self.client
            if self.client is None or time.time() >= self.expires - 300:
                if self.credential is None:
                    raise ValueError("An Azure credential is required for cloud Redis")
                token = await self.credential.get_token(self.settings.redis_scope)
                if self.client:
                    await self.client.aclose()
                self.client = Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    username=self.settings.redis_username,
                    password=token.token,
                    ssl=True,
                    decode_responses=True,
                    socket_timeout=10,
                    socket_connect_timeout=10,
                )
                self.expires = token.expires_on
            return self.client

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[None]:
        client = await self.connection()
        lock = client.lock(self.lock_key, timeout=300, blocking_timeout=30)
        if not await lock.acquire():
            raise OSError("Could not acquire usage-ledger lock")
        try:
            yield
        finally:
            try:
                await lock.release()
            except RedisError:
                # The durable ledger is authoritative; a lost release expires by TTL.
                emit("counter_lock_release_deferred", error_type="RedisError")

    @observe_dependency("redis", "project")
    async def project(self, records: list[Record]) -> None:
        projection: dict[str, int] = {}
        for record in records:
            data = record.get("data", {})
            amount = data.get("cost_micro_usd")
            if not isinstance(amount, int):
                continue
            for key in data.get("projection_keys", []):
                projection[key] = projection.get(key, 0) + amount
        client = await self.connection()
        await client.eval(
            REPLACE_PROJECTION,
            1,
            self.projection_key,
            json.dumps(projection, separators=(",", ":")),
        )

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()
