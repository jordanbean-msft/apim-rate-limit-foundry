import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import UpdateMode

from apim_rate_limit_foundry.stores.memory import MemoryRepository
from apim_rate_limit_foundry.stores.table import TableRepository
from apim_rate_limit_foundry.telemetry.service_requests import record_table_response


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


async def test_table_usage_history_is_written_and_queried_by_partition() -> None:
    record = {"id": "request", "data": {"month": "2030-01"}}
    client = MagicMock()
    client.create_entity = AsyncMock(side_effect=[None, ResourceExistsError("duplicate")])
    client.get_entity = AsyncMock(return_value={"payload": json.dumps(record)})

    async def entities(*args, **kwargs):
        yield {"payload": json.dumps(record)}

    client.query_entities = MagicMock(side_effect=entities)
    repository = TableRepository(client)
    partition = "usage:tenant-1:2030-01"

    await repository.create_if_absent("usage_v2", "request", record, partition)
    await repository.create_if_absent("usage_v2", "request", record, partition)
    rows = await repository.list("usage_v2", partition)

    assert client.create_entity.await_args_list[0].args[0]["PartitionKey"] == partition
    client.get_entity.assert_awaited_once_with(
        partition,
        TableRepository.entity("usage_v2", "request", record)["RowKey"],
        raw_response_hook=record_table_response,
    )
    assert rows == [record]
    query = client.query_entities.call_args
    assert query.args[0] == "PartitionKey eq @partition and collection eq @collection"
    assert query.kwargs["parameters"] == {"partition": partition, "collection": "usage_v2"}


async def test_table_configuration_lists_stay_in_the_ledger_partition() -> None:
    client = MagicMock()

    async def entities(*args, **kwargs):
        return
        yield

    client.query_entities = MagicMock(side_effect=entities)

    await TableRepository(client).list("budgets")

    assert client.query_entities.call_args.kwargs["parameters"]["partition"] == "ledger"


async def test_memory_repository_isolates_partitions() -> None:
    repository = MemoryRepository()
    await repository.create("usage_v2", "same-id", {"id": "a"}, "usage:t:2030-01")
    await repository.create("usage_v2", "same-id", {"id": "b"}, "usage:t:2030-02")
    await repository.create("usage_v2", "same-id", {"id": "ledger"})

    assert await repository.list("usage_v2", "usage:t:2030-01") == [{"id": "a"}]
    assert await repository.list("usage_v2", "usage:t:2030-02") == [{"id": "b"}]
    assert await repository.list("usage_v2") == [{"id": "ledger"}]
    assert await repository.get("usage_v2", "same-id", "usage:t:2030-02") == {"id": "b"}
    assert await repository.get("usage_v2", "same-id", "usage:t:2031-01") is None


async def test_table_get_returns_none_for_missing_entities_and_decodes_payloads() -> None:
    record = {"id": "request"}
    client = MagicMock()
    client.get_entity = AsyncMock(
        side_effect=[ResourceNotFoundError("missing"), {"payload": json.dumps(record)}]
    )
    repository = TableRepository(client)

    assert await repository.get("budgets", "request") is None
    assert await repository.get("budgets", "request") == record


async def test_table_create_returns_the_winning_record() -> None:
    client = MagicMock()
    client.create_entity = AsyncMock(return_value=None)

    saved = await TableRepository(client).create("budgets", "b", {"id": "b"})

    assert saved == {"id": "b"}


async def test_table_duplicate_whose_winner_vanished_is_an_error_not_a_create() -> None:
    client = MagicMock()
    client.create_entity = AsyncMock(side_effect=ResourceExistsError("duplicate"))
    client.get_entity = AsyncMock(side_effect=ResourceNotFoundError("gone"))

    with pytest.raises(RuntimeError, match="disappeared"):
        await TableRepository(client).create_if_absent("budgets", "b", {"id": "b"})


async def test_table_mutation_commits_audit_and_replacement_in_one_transaction() -> None:
    client = MagicMock()
    client.submit_transaction = AsyncMock()
    repository = TableRepository(client)

    await repository.mutate("budgets", "b", {"id": "b", "limit": 1}, {"id": "audit-1"})
    await repository.mutate("budgets", "b", None, {"note": "no id"})

    replace, delete = (call.args[0] for call in client.submit_transaction.await_args_list)
    assert [op[0] for op in replace] == ["create", "upsert"]
    assert json.loads(replace[1][1]["payload"]) == {"id": "b", "limit": 1}
    assert replace[1][2] == {"mode": UpdateMode.REPLACE}
    assert replace[0][1]["RowKey"] == TableRepository.entity("audit", "audit-1", {})["RowKey"]
    assert json.loads(delete[1][1]["payload"]) == {"id": "b", "_deleted": True}
    assert delete[0][1]["collection"] == "audit"


async def test_table_close_releases_the_client() -> None:
    client = MagicMock()
    client.close = AsyncMock()

    await TableRepository(client).close()

    client.close.assert_awaited_once()
