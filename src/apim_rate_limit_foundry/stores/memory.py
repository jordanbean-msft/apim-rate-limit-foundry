import asyncio
import time
from copy import deepcopy
from uuid import uuid4

from apim_rate_limit_foundry.stores.contracts import Conflict, Record, RecoveryRequired


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
        return [deepcopy(v) for (c, _), v in self.records.items() if c == collection]

    async def create(self, collection: str, record_id: str, record: Record) -> Record:
        self.check()
        return deepcopy(self.records.setdefault((collection, record_id), deepcopy(record)))

    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
        self.check()
        if record is None:
            self.records.pop((collection, record_id), None)
        else:
            self.records[collection, record_id] = deepcopy(record)
        self.records["audit", audit["id"]] = deepcopy(audit)

    async def close(self) -> None:
        pass


class MemoryCounters:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.token = ""
        self.recovering_until = 0.0
        self.counts: dict[str, int] = {}
        self.reservations: dict[str, Record] = {}
        self.lock = asyncio.Lock()

    def check(self) -> None:
        if not self.ready:
            raise RecoveryRequired("Redis recovery required")

    async def reserve(
        self, reservation_id: str, fingerprint: str, debits: list[Record], decision: Record
    ) -> Record:
        async with self.lock:
            self.check()
            if old := self.reservations.get(reservation_id):
                if old["fingerprint"] != fingerprint:
                    raise Conflict("Request ID reused with different request")
                return deepcopy(old["decision"])
            allowed = all(self.counts.get(d["key"], 0) + d["amount"] <= d["limit"] for d in debits)
            remaining = min(
                d["limit"] - self.counts.get(d["key"], 0) - (d["amount"] if allowed else 0)
                for d in debits
            )
            result = {
                **decision,
                "allowed": allowed,
                "remaining": max(0, remaining),
                "reason": "reserved" if allowed else "budget_exhausted",
            }
            self.reservations[reservation_id] = {
                "fingerprint": fingerprint,
                "debits": debits if allowed else [],
                "decision": result,
                "final": "",
            }
            if allowed:
                for d in debits:
                    self.counts[d["key"]] = self.counts.get(d["key"], 0) + d["amount"]
            return deepcopy(result)

    async def finalize(self, reservation_id: str, debits: list[Record], fingerprint: str) -> Record:
        async with self.lock:
            self.check()
            old = self.reservations.get(reservation_id)
            if old is None or not old["decision"]["allowed"]:
                raise Conflict("Unknown reservation")
            if old["final"]:
                if old["final"] != fingerprint:
                    raise Conflict("Reservation already finalized differently")
                return deepcopy(old)
            for before, after in zip(old["debits"], debits, strict=True):
                self.counts[before["key"]] += after["amount"] - before["amount"]
            old["debits"] = deepcopy(debits)
            old["final"] = fingerprint
            return deepcopy(old)

    async def begin_recovery(self) -> str:
        async with self.lock:
            if self.token and self.recovering_until > time.monotonic():
                raise Conflict("Recovery already in progress")
            self.ready = False
            self.token = uuid4().hex
            self.recovering_until = time.monotonic() + 300
            return self.token

    async def recover(self, token: str, records: list[Record]) -> None:
        async with self.lock:
            if token != self.token:
                raise Conflict("Recovery lock lost")
            self.counts.clear()
            self.reservations.clear()
            for record in records:
                self.reservations[record["id"]] = deepcopy(record["counter"])
                for d in record["counter"]["debits"]:
                    self.counts[d["key"]] = self.counts.get(d["key"], 0) + d["amount"]
            self.token = ""
            self.ready = True

    async def close(self) -> None:
        pass
