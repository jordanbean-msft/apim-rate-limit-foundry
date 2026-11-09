import json
from unittest.mock import AsyncMock, MagicMock

from azure.core.exceptions import ResourceExistsError

from apim_rate_limit_foundry.stores.table import TableRepository


async def test_table_create_if_absent_is_durable_and_idempotent() -> None:
    record = {"id": "request", "kind": "usage", "data": {"event_version": 2}}
    client = MagicMock()
    client.create_entity = AsyncMock(side_effect=[None, ResourceExistsError("duplicate")])
    client.get_entity = AsyncMock(return_value={"payload": json.dumps(record)})
    repository = TableRepository(client)

    created, inserted = await repository.create_if_absent("usage_v2", "request", record)
    replay, inserted_again = await repository.create_if_absent(
        "usage_v2", "request", {"id": "request", "data": {"event_version": 1}}
    )

    assert created == replay == record
    assert inserted is True
    assert inserted_again is False
    assert client.create_entity.await_count == 2
    assert client.get_entity.await_count == 1


def test_table_entity_key_hashes_collection_and_record_identity() -> None:
    entity = TableRepository.entity("usage_v2", "request-123", {"id": "record"})
    assert entity["PartitionKey"] == "ledger"
    assert entity["RowKey"] != "request-123"
    assert entity["collection"] == "usage_v2"
