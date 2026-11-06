import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from azure.identity.aio import DefaultAzureCredential
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores import scripts
from apim_rate_limit_foundry.stores.contracts import Conflict, Record, RecoveryRequired
from apim_rate_limit_foundry.telemetry import observe_dependency


class RedisCounters:
    """One hash tag and one eviction unit prevent cross-slot and partial-key cache loss."""

    key = "{limiter}:ledger"

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
        self.lock = asyncio.Lock()

    @classmethod
    def from_url(cls, settings: Settings, url: str) -> "RedisCounters":
        if not settings.local_store_enabled or settings.in_azure:
            raise ValueError("Redis URLs are only permitted in explicit local store mode")
        return cls(
            settings,
            None,
            Redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=10,
            ),
        )

    async def connection(self) -> Redis:
        async with self.lock:
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

    async def execute(self, script: str, *args: str) -> Any:
        client = await self.connection()
        try:
            return await client.eval(script, 1, self.key, *args)
        except ResponseError as error:
            if "RECOVERY_REQUIRED" in str(error):
                raise RecoveryRequired(
                    "Cache cold start; administrator recovery required"
                ) from error
            if "CONFLICT" in str(error):
                raise Conflict("Idempotency or recovery conflict") from error
            raise

    @observe_dependency("redis", "reserve")
    async def reserve(
        self, reservation_id: str, fingerprint: str, debits: list[Record], decision: Record
    ) -> Record:
        return json.loads(
            await self.execute(
                scripts.RESERVE,
                reservation_id,
                fingerprint,
                json.dumps(debits),
                json.dumps(decision),
            )
        )

    @observe_dependency("redis", "finalize")
    async def finalize(self, reservation_id: str, debits: list[Record], fingerprint: str) -> Record:
        return json.loads(
            await self.execute(scripts.FINALIZE, reservation_id, json.dumps(debits), fingerprint)
        )

    @observe_dependency("redis", "begin_recovery")
    async def begin_recovery(self) -> str:
        token = uuid4().hex
        await self.execute(scripts.BEGIN_RECOVERY, token)
        return token

    @observe_dependency("redis", "recover")
    async def recover(self, token: str, records: list[Record]) -> None:
        await self.execute(scripts.RECOVER, token, json.dumps(records))

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()
