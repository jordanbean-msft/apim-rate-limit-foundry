"""Azure Table persistence for configuration, audit and best-effort request history.

This repository is not in the warm admission/accounting path. The engine mirrors
request and usage records asynchronously, so durable history can be incomplete.
"""

import json
from typing import Any
from uuid import uuid4

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.stores.contracts import LEDGER_PARTITION, Record
from apim_rate_limit_foundry.stores.create_once import CreateOnceRepository
from apim_rate_limit_foundry.telemetry import emit, observe_dependency


class TableRepository(CreateOnceRepository):
    """Ledger-partition records allow atomic configuration-plus-audit transactions.

    Usage history is keyed by its own tenant/month partition, so reports query one
    partition instead of filtering every row. History written before this keying
    sits in the ledger partition and is not read or migrated (sample scope).
    """

    def __init__(self, client: TableClient) -> None:
        """Bind the Table client whose lifetime is closed with this repository."""
        self.client = client

    @staticmethod
    def entity(
        collection: str, record_id: str, record: Record, partition: str = LEDGER_PARTITION
    ) -> Record:
        """Encode a JSON payload under a hashed collection/ID row in a partition."""
        return {
            "PartitionKey": partition,
            "RowKey": digest(collection, record_id),
            "collection": collection,
            "payload": json.dumps(record, separators=(",", ":")),
        }

    @observe_dependency("table", "get")
    async def get(
        self, collection: str, record_id: str, partition: str = LEDGER_PARTITION
    ) -> Record | None:
        """Return decoded payload or None for a missing entity; other errors propagate."""
        try:
            entity = await self.client.get_entity(partition, digest(collection, record_id))
        except ResourceNotFoundError:
            emit("durable_record_read", collection=collection, status="not_found")
            return None
        return json.loads(entity["payload"])

    @observe_dependency("table", "list")
    async def list(self, collection: str, partition: str = LEDGER_PARTITION) -> list[Record]:
        """Materialize one partition's matching pages, leaving tombstone filtering to callers."""
        entities = self.client.query_entities(
            "PartitionKey eq @partition and collection eq @collection",
            parameters={"partition": partition, "collection": collection},
        )
        return [json.loads(e["payload"]) async for e in entities]

    @observe_dependency("table", "create_if_absent")
    async def create_if_absent(
        self, collection: str, record_id: str, record: Record, partition: str = LEDGER_PARTITION
    ) -> tuple[Record, bool]:
        """Create a record or read its existing winner and return a creation flag.

        Duplicate payload equality is not checked here. A record disappearing
        between conflict and read is an explicit error, not a successful create.
        """
        try:
            await self.client.create_entity(self.entity(collection, record_id, record, partition))
            return record, True
        except ResourceExistsError:
            emit("durable_record_replayed", collection=collection, replayed=True)
            existing = await self.get(collection, record_id, partition)
            if existing is None:
                raise RuntimeError("Durable record disappeared") from None
            return existing, False

    @observe_dependency("table", "mutate")
    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
        """Atomically create an audit row and replace configuration in one partition.

        ``None`` writes a tombstone rather than deleting the entity. Cache
        invalidation is deliberately outside this durable transaction, owned by
        the engine. Transaction failures propagate without a partial audit pair.
        """
        operations: list[Any] = [
            ("create", self.entity("audit", audit.get("id", uuid4().hex), audit))
        ]
        if record is None:
            # A tombstone makes repeated DELETE idempotent and keeps its audit atomic.
            record = {"id": record_id, "_deleted": True}
        operations.append(
            ("upsert", self.entity(collection, record_id, record), {"mode": UpdateMode.REPLACE})
        )
        await self.client.submit_transaction(operations)

    async def close(self) -> None:
        """Release the injected Table client's transport resources."""
        await self.client.close()
