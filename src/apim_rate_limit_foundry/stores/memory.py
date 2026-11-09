import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy

from apim_rate_limit_foundry.stores.contracts import Record


class MemoryRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], Record] = {}
        self.fail = False

    def check(self) -> None:
        if self.fail:
            raise OSError("Injected durable storage failure")

    async def get(self, collection: str, record_id: str) -> Record | None:
        self.check()
        return deepcopy(self.records.get((collection, record_id)))

    async def list(self, collection: str) -> list[Record]:
        self.check()
        return [deepcopy(value) for (name, _), value in self.records.items() if name == collection]

    async def create(self, collection: str, record_id: str, record: Record) -> Record:
        saved, _ = await self.create_if_absent(collection, record_id, record)
        return saved

    async def create_if_absent(
        self, collection: str, record_id: str, record: Record
    ) -> tuple[Record, bool]:
        self.check()
        key = (collection, record_id)
        existing = self.records.get(key)
        if existing is not None:
            return deepcopy(existing), False
        self.records[key] = deepcopy(record)
        return deepcopy(record), True

    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
        self.check()
        key = (collection, record_id)
        self.records[key] = (
            deepcopy(record) if record is not None else {"id": record_id, "_deleted": True}
        )
        self.records["audit", audit["id"]] = deepcopy(audit)

    async def close(self) -> None:
        pass


class MemoryCounters:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.lock = asyncio.Lock()
        self.ready = True

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[None]:
        if not self.ready:
            raise OSError("Counter projection unavailable")
        async with self.lock:
            yield

    async def project(self, records: list[Record]) -> None:
        self.counts.clear()
        for record in records:
            data = record.get("data", {})
            amount = data.get("cost_micro_usd")
            if not isinstance(amount, int):
                continue
            for key in data.get("projection_keys", []):
                self.counts[key] = self.counts.get(key, 0) + amount

    async def close(self) -> None:
        pass
