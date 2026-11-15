"""Store boundaries separating durable history from disposable live budget state."""

from typing import Any, Protocol

Record = dict[str, Any]


class Repository(Protocol):
    """Durable records; configuration mutations include an atomic audit write.

    Storage errors propagate. Reads may include tombstones, leaving visibility
    and tenant filtering to the engine. Record creation never replaces an ID.
    """

    async def get(self, collection: str, record_id: str) -> Record | None:
        """Return the stored record (including tombstones), or None when absent."""
        ...

    async def list(self, collection: str) -> list[Record]:
        """Return collection records without application visibility filtering."""
        ...

    async def create(self, collection: str, record_id: str, record: Record) -> Record:
        """Create once, returning the existing record if the ID already exists."""
        ...

    async def create_if_absent(
        self, collection: str, record_id: str, record: Record
    ) -> tuple[Record, bool]:
        """Return (winning record, created), without comparing replay payloads."""
        ...

    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
        """Atomically replace/tombstone configuration and create its audit event."""
        ...

    async def close(self) -> None:
        """Release owned storage-client resources."""
        ...


class CounterStore(Protocol):
    """Live cache, replay window and spend; failures must not fall back to Table.

    Request IDs address shared keys directly, so callers must avoid cross-tenant
    ID collisions and verify stored fingerprints. Losing state may reset spend
    or remove replay/context protection; these records are not a durable ledger.
    """

    async def configuration(self) -> Record | None:
        """Return the cached snapshot, or None after expiry/absence."""
        ...

    async def cache_configuration(self, snapshot: Record) -> None:
        """Replace the shared configuration snapshot with the configured TTL."""
        ...

    async def invalidate_configuration(self) -> None:
        """Remove the shared snapshot after a durable administrative mutation."""
        ...

    async def request(self, request_id: str) -> Record | None:
        """Read an unexpired admission context, with no durable recovery."""
        ...

    async def admit(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Store context only if absent; return (winning context, created)."""
        ...

    async def usage(self, request_id: str) -> Record | None:
        """Read a finalized usage record while replay protection remains live."""
        ...

    async def record(self, request_id: str, record: Record) -> tuple[Record, bool]:
        """Atomically save first usage and increment its integer-cost counter keys.

        Return (winning record, created); replays must not increment again.
        Unknown costs are recorded without incrementing spend.
        """
        ...

    async def totals(self, month: str, keys: list[str]) -> dict[str, int]:
        """Return micro-USD by requested counter key, using zero for absent counters."""
        ...

    async def close(self) -> None:
        """Release operational-client resources."""
        ...


class Conflict(ValueError):  # noqa: N818
    """Signal an incompatible identity, replay or record state to the API boundary."""

    pass
