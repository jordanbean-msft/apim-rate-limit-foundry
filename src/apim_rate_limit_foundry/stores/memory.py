"""Deterministic in-process store substitutes for local use and failure-path tests.

Deep copies prevent callers from mutating saved admission/configuration snapshots.
No data survives process exit; these substitutes are not multi-worker storage.
"""

import time
from copy import deepcopy

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.contracts import LEDGER_PARTITION, Record
from apim_rate_limit_foundry.stores.create_once import CreateOnceRepository


class MemoryRepository(CreateOnceRepository):
    """Emulate create-once records and audited replacements without external I/O."""

    def __init__(self) -> None:
        """Initialize isolated records and an opt-in durable-failure injection flag."""
        self.records: dict[tuple[str, str, str], Record] = {}
        self.fail = False

    def check(self) -> None:
        """Raise the simulated storage outage before accessing durable records."""
        if self.fail:
            raise OSError("Injected durable storage failure")

    async def get(
        self, collection: str, record_id: str, partition: str = LEDGER_PARTITION
    ) -> Record | None:
        """Return a detached record, including tombstones, or None."""
        self.check()
        return deepcopy(self.records.get((partition, collection, record_id)))

    async def list(self, collection: str, partition: str = LEDGER_PARTITION) -> list[Record]:
        """Return detached partition records without filtering tombstones or tenants."""
        self.check()
        return [
            deepcopy(value)
            for (owner, name, _), value in self.records.items()
            if owner == partition and name == collection
        ]

    async def create_if_absent(
        self, collection: str, record_id: str, record: Record, partition: str = LEDGER_PARTITION
    ) -> tuple[Record, bool]:
        """Save a detached first value and report whether this call created it."""
        self.check()
        key = (partition, collection, record_id)
        existing = self.records.get(key)
        if existing is not None:
            return deepcopy(existing), False
        self.records[key] = deepcopy(record)
        return deepcopy(record), True

    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
        """Replace/tombstone configuration and save its audit without an intervening await."""
        self.check()
        key = (LEDGER_PARTITION, collection, record_id)
        self.records[key] = (
            deepcopy(record) if record is not None else {"id": record_id, "_deleted": True}
        )
        self.records[LEDGER_PARTITION, "audit", audit["id"]] = deepcopy(audit)

    async def close(self) -> None:
        pass


class MemoryCounters:
    """Emulate live replay TTLs and increments in a single event loop.

    TTL checks use monotonic time and leave expired entries allocated. Unlike
    Redis, spend dictionaries do not expire; their keys already include the month.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize isolated state, configured cache lifetimes and an outage switch."""
        self.settings = settings or Settings()
        self.counts: dict[str, int] = {}
        self.requests: dict[str, tuple[float, Record]] = {}
        self.usages: dict[str, tuple[float, Record]] = {}
        self.snapshot: tuple[float, Record] | None = None
        self.ready = True

    def _check(self) -> None:
        """Simulate an unavailable operational dependency when readiness is disabled."""
        if not self.ready:
            raise OSError("Operational cache unavailable")

    async def configuration(self) -> Record | None:
        """Read a detached snapshot only while its configured lifetime remains valid."""
        self._check()
        if self.snapshot is None or self.snapshot[0] <= time.monotonic():
            return None
        return deepcopy(self.snapshot[1])

    async def cache_configuration(self, snapshot: Record) -> None:
        """Replace the snapshot with a deep copy and a fresh monotonic expiry."""
        self._check()
        self.snapshot = self._expiring(self.settings.configuration_cache_seconds, snapshot)

    async def invalidate_configuration(self) -> None:
        """Discard the snapshot so the next engine check reloads durable configuration."""
        self._check()
        self.snapshot = None

    @staticmethod
    def _expiring(seconds: int, record: Record) -> tuple[float, Record]:
        """Pair a detached copy with its monotonic expiry."""
        return time.monotonic() + seconds, deepcopy(record)

    def _get(self, records: dict[str, tuple[float, Record]], key: str) -> Record | None:
        """Read a detached, unexpired replay value or return None."""
        self._check()
        entry = records.get(key)
        if entry is None or entry[0] <= time.monotonic():
            return None
        return deepcopy(entry[1])

    async def request(self, request_id: str) -> Record | None:
        """Read live admission context keyed by the raw request ID."""
        return self._get(self.requests, request_id)

    async def admit(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Pin the first unexpired decision; duplicate admission does not refresh its TTL."""
        prior = await self.request(request_id)
        if prior is not None:
            return prior, False
        self.requests[request_id] = self._expiring(self.settings.request_cache_seconds, record)
        return deepcopy(record), True

    async def usage(self, request_id: str) -> Record | None:
        """Read finalized usage within the configured request replay window."""
        return self._get(self.usages, request_id)

    async def record(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Increment known-cost projections once and pin the winning usage payload.

        Awaited memory reads do not suspend, so mutation is indivisible within one
        event loop. Unknown costs retain replay protection without changing spend.
        """
        prior = await self.usage(request_id)
        if prior is not None:
            return prior, False
        data = record["data"]
        amount = data.get("cost_micro_usd")
        if isinstance(amount, int):
            for key in data.get("counter_keys", []):
                self.counts[key] = self.counts.get(key, 0) + amount
        self.usages[request_id] = self._expiring(self.settings.request_cache_seconds, record)
        return deepcopy(record), True

    async def totals(self, month: str, keys: list[str]) -> dict[str, int]:
        """Return current values; month is already encoded in the supplied digest keys."""
        self._check()
        return {key: self.counts.get(key, 0) for key in keys}

    async def close(self) -> None:
        pass
