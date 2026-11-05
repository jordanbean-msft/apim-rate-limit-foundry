import json
from typing import Any
from uuid import uuid4

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.stores.contracts import Record


class TableRepository:
    """Single-partition records allow atomic configuration-plus-audit transactions."""

    def __init__(self, client: TableClient) -> None:
        self.client = client

    @staticmethod
    def entity(collection: str, record_id: str, record: Record) -> Record:
        return {
            "PartitionKey": "ledger",
            "RowKey": digest(collection, record_id),
            "collection": collection,
            "payload": json.dumps(record, separators=(",", ":")),
        }

    async def get(self, collection: str, record_id: str) -> Record | None:
        try:
            entity = await self.client.get_entity("ledger", digest(collection, record_id))
        except ResourceNotFoundError:
            return None
        return json.loads(entity["payload"])

    async def list(self, collection: str) -> list[Record]:
        entities = self.client.query_entities(
            "PartitionKey eq 'ledger' and collection eq @collection",
            parameters={"collection": collection},
        )
        return [json.loads(e["payload"]) async for e in entities]

    async def create(self, collection: str, record_id: str, record: Record) -> Record:
        try:
            await self.client.create_entity(self.entity(collection, record_id, record))
            return record
        except ResourceExistsError:
            existing = await self.get(collection, record_id)
            if existing is None:
                raise RuntimeError("Durable record disappeared") from None
            return existing

    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None:
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
        await self.client.close()
