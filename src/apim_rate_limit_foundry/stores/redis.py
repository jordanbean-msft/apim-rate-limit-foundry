"""Redis operational state with explicit TTLs and atomic incremental accounting.

All keys share the ``{limiter}`` cluster hash tag so usage and monthly spend can
participate in one Lua invocation. Redis is authoritative for live enforcement:
errors propagate and lost state is not reconstructed from durable history.
"""

import asyncio
import json
import time

from azure.identity.aio import DefaultAzureCredential
from redis.asyncio import Redis

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.stores.contracts import Record
from apim_rate_limit_foundry.stores.scripts import RECORD_USAGE
from apim_rate_limit_foundry.telemetry import observe_dependency


class RedisCounters:
    """Cache snapshots/context and maintain monthly micro-USD hash projections.

    Configuration and request/usage lifetimes come from settings; spend hashes
    expire 62 days after their latest known-cost write. Replay deduplication lasts
    only for the usage-key lifetime and does not guarantee durable exactly-once work.
    """

    configuration_key = "{limiter}:configuration:v3"
    counter_retention_seconds = 62 * 24 * 60 * 60

    def __init__(
        self,
        settings: Settings,
        credential: DefaultAzureCredential | None,
        client: Redis | None = None,
    ) -> None:
        """Accept an injected client or lazily create an Entra-authenticated connection."""
        self.settings = settings
        self.credential = ObservedCredential(credential) if credential is not None else None
        self.client = client
        self.static_client = client is not None
        self.expires = 0
        self.retired: list[Redis] = []
        self.connection_lock = asyncio.Lock()

    @classmethod
    def from_url(cls, settings: Settings, url: str) -> "RedisCounters":
        """Build a URL-based test/local client only when explicit local mode permits it."""
        if not settings.local_store_enabled or settings.in_azure:
            raise ValueError("Redis URLs are only permitted in explicit local store mode")
        return cls(
            settings,
            None,
            Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2),
        )

    @observe_dependency("redis", "connection")
    async def connection(self) -> Redis:
        """Return the live client, refreshing its Entra token five minutes before expiry.

        One caller renews the token; while it does, others keep using the still-valid
        client instead of queueing, so commands are not serialized behind a lock. Only
        a missing or fully expired client waits for the refresh. Injected clients
        bypass credential refresh. Redis I/O uses two-second socket/connect timeouts;
        credential and connection errors reach callers.
        """
        if self.static_client:
            assert self.client is not None
            return self.client
        if self.client is None or (self._expiring() and not self._valid_while_refreshing()):
            await self._refresh()
        assert self.client is not None
        return self.client

    def _valid_while_refreshing(self) -> bool:
        """Report whether another caller is renewing a token that has not yet expired."""
        return self.connection_lock.locked() and time.time() < self.expires

    def _expiring(self) -> bool:
        """Report whether the token must be renewed before it can serve more commands."""
        return time.time() >= self.expires - 300

    async def _refresh(self) -> None:
        """Swap in a client with a fresh token and defer closing the one it replaces.

        In-flight commands may still be using the old client, so it is retired and
        closed only at the next refresh (a full token lifetime later) or on close().
        """
        async with self.connection_lock:
            if self.client is not None and not self._expiring():
                return
            if self.credential is None:
                raise ValueError("An Azure credential is required for cloud Redis")
            token = await self.credential.get_token(self.settings.redis_scope)
            previous = self.client
            self.client = Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                username=self.settings.redis_username,
                password=token.token,
                ssl=True,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
            self.expires = token.expires_on
            stale, self.retired = self.retired, [previous] if previous else []
            for client in stale:
                await client.aclose()

    @observe_dependency("redis", "configuration")
    async def configuration(self) -> Record | None:
        """Deserialize the shared configuration snapshot, returning None on a cache miss."""
        client = await self.connection()
        value = await client.get(self.configuration_key)
        return json.loads(value) if value is not None else None

    async def cache_configuration(self, snapshot: Record) -> None:
        """Serialize a detached snapshot and reset its configured cache TTL."""
        client = await self.connection()
        await client.set(
            self.configuration_key,
            json.dumps(snapshot, separators=(",", ":")),
            ex=self.settings.configuration_cache_seconds,
        )

    async def invalidate_configuration(self) -> None:
        """Delete the shared snapshot after durable configuration changes."""
        client = await self.connection()
        await client.delete(self.configuration_key)

    @observe_dependency("redis", "request")
    async def request(self, request_id: str) -> Record | None:
        """Read admission context directly, without refreshing its expiry or consulting Table."""
        client = await self.connection()
        value = await client.get(f"{{limiter}}:request:v3:{request_id}")
        return json.loads(value) if value is not None else None

    @observe_dependency("redis", "admit")
    async def admit(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Use SET NX with TTL to choose one admission snapshot per raw request ID.

        A duplicate returns the winner for engine-level fingerprint validation.
        If the winner expires before that read, fail explicitly instead of
        treating the duplicate as a fresh successful admission.
        """
        client = await self.connection()
        created = await client.set(
            f"{{limiter}}:request:v3:{request_id}",
            json.dumps(record, separators=(",", ":")),
            ex=self.settings.request_cache_seconds,
            nx=True,
        )
        if created:
            return record, True
        prior = await self.request(request_id)
        if prior is None:
            raise OSError("Admission context expired during replay")
        return prior, False

    @observe_dependency("redis", "usage")
    async def usage(self, request_id: str) -> Record | None:
        """Read the finalized usage replay value without extending the replay window."""
        client = await self.connection()
        value = await client.get(f"{{limiter}}:usage:v3:{request_id}")
        return json.loads(value) if value is not None else None

    @observe_dependency("redis", "record")
    async def record(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Execute first-usage deduplication and all hierarchy increments in one script.

        Supply a usage key, monthly hash and serialized record/TTLs/cost/fields.
        Unknown cost supplies no fields: it finalizes replay state without spend.
        Return (winning record, created); payload compatibility is checked by the
        engine. Atomic execution prevents interleaving, not Redis error rollback.
        """
        data = record["data"]
        amount = data.get("cost_micro_usd")
        keys = data["counter_keys"] if isinstance(amount, int) else []
        client = await self.connection()
        result = await client.eval(
            RECORD_USAGE,
            2,
            f"{{limiter}}:usage:v3:{request_id}",
            f"{{limiter}}:spend:v3:{data['month']}",
            json.dumps(record, separators=(",", ":")),
            self.settings.request_cache_seconds,
            self.counter_retention_seconds,
            str(amount if isinstance(amount, int) else 0),
            json.dumps(keys, separators=(",", ":")),
        )
        return json.loads(result[0]), bool(result[1])

    @observe_dependency("redis", "totals")
    async def totals(self, month: str, keys: list[str]) -> dict[str, int]:
        """Fetch requested monthly hash fields in one call, treating missing spend as zero."""
        if not keys:
            return {}
        client = await self.connection()
        values = await client.hmget(f"{{limiter}}:spend:v3:{month}", keys)
        return {
            key: int(value) if value is not None else 0
            for key, value in zip(keys, values, strict=True)
        }

    async def close(self) -> None:
        """Close current and retired Redis clients; the shared credential remains caller-owned."""
        for client in [*self.retired, *([self.client] if self.client else [])]:
            await client.aclose()
        self.retired = []
