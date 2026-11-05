import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from redis.exceptions import ResponseError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository
from apim_rate_limit_foundry.telemetry import JsonFormatter


async def test_table_create_collision_read_list_and_atomic_audit() -> None:
    client = AsyncMock()
    repository = TableRepository(client)
    record = {"id": "p", "name": "Policy"}
    assert await repository.create("policies", "p", record) == record
    entity = client.create_entity.call_args.args[0]
    assert json.loads(entity["payload"]) == record
    client.create_entity.side_effect = ResourceExistsError()
    client.get_entity.return_value = entity
    assert await repository.create("policies", "p", {"id": "p", "name": "different"}) == record
    client.get_entity.side_effect = ResourceNotFoundError()
    assert await repository.get("policies", "missing") is None

    async def entities():
        yield entity

    client.query_entities = MagicMock(return_value=entities())
    assert await repository.list("policies") == [record]
    audit = {"id": "audit", "actor": "admin"}
    await repository.mutate("policies", "p", record, audit)
    operations = client.submit_transaction.call_args.args[0]
    assert len(operations) == 2
    assert operations[0][0] == "create"
    assert operations[1][0] == "upsert"
    assert operations[0][1]["PartitionKey"] == operations[1][1]["PartitionKey"]
    await repository.mutate("policies", "p", None, audit)
    tombstone = client.submit_transaction.call_args.args[0][1][1]
    assert json.loads(tombstone["payload"])["_deleted"]
    client.submit_transaction.side_effect = OSError("transaction failed")
    with pytest.raises(OSError):
        await repository.mutate("policies", "p", record, audit)
    await repository.close()
    client.close.assert_awaited_once()


async def test_redis_renews_entra_token_and_recycles_connections(settings: Settings) -> None:
    credential = AsyncMock()
    credential.get_token.return_value = SimpleNamespace(
        token="fresh", expires_on=time.time() + 3600
    )
    counters = RedisCounters(settings, credential)
    previous = AsyncMock()
    counters.client = previous
    counters.expires = time.time() + 10
    with patch("apim_rate_limit_foundry.stores.redis.Redis") as redis_class:
        redis_class.return_value = AsyncMock()
        client = await counters.connection()
        previous.aclose.assert_awaited_once()
        credential.get_token.assert_awaited_with("https://redis.azure.com/.default")
        assert redis_class.call_args.kwargs["ssl"] is True
        assert redis_class.call_args.kwargs["password"] == "fresh"
        assert await counters.connection() is client
        assert credential.get_token.await_count == 1
        client.eval.side_effect = ResponseError("unrecognized failure")
        with pytest.raises(ResponseError):
            await counters.execute("return 1")
        await counters.close()


async def test_cloud_runtime_constructs_real_clients_and_closes(settings: Settings) -> None:
    production = settings.model_copy(
        update={
            "local_store_enabled": False,
            "table_endpoint": "https://example.table.core.windows.net",
            "redis_host": "redis.example",
            "redis_username": "object-id",
            "azure_client_id": "client-id",
        }
    )
    with (
        patch("apim_rate_limit_foundry.runtime.DefaultAzureCredential") as credential_class,
        patch("apim_rate_limit_foundry.runtime.TableClient") as table_class,
    ):
        credential_class.return_value = AsyncMock()
        table_class.return_value = AsyncMock()
        runtime = Runtime(production)
        assert isinstance(runtime.engine.repository, TableRepository)
        assert isinstance(runtime.engine.counters, RedisCounters)
        assert credential_class.call_args.kwargs["managed_identity_client_id"] == "client-id"
        assert table_class.call_args.kwargs["audience"] == "https://storage.azure.com"
        await runtime.close()
        credential_class.return_value.close.assert_awaited_once()
    with pytest.raises(ValueError, match="required"):
        Runtime(Settings(_env_file=None))


def test_structured_logs_only_emit_allowlisted_context() -> None:
    record = logging.LogRecord("limiter", logging.INFO, "", 0, "decision", (), None)
    record.reservation_id = "reservation"
    record.allowed = True
    record.prompt = "must not log"
    payload = json.loads(JsonFormatter().format(record))
    assert payload == {
        "level": "INFO",
        "event": "decision",
        "reservation_id": "reservation",
        "allowed": True,
    }
