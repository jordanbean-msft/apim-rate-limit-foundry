import os
from uuid import uuid4

import pytest
from azure.data.tables.aio import TableClient

from apim_rate_limit_foundry.stores.table import TableRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_AZURITE") != "true",
    reason="Set TEST_AZURITE=true for the local Azure Tables emulator",
)


async def test_real_table_sdk_preserves_events_and_atomic_config_audit() -> None:
    async with TableClient.from_connection_string(
        "UseDevelopmentStorage=true", table_name=f"Integration{uuid4().hex}"
    ) as table:
        await table.create_table()
        repository = TableRepository(table)
        try:
            original = {"id": "request", "data": {"amount": 100}}
            assert await repository.create("usage", "request", original) == original
            assert (
                await repository.create("usage", "request", {"id": "request", "data": {}})
                == original
            )
            assert await repository.list("usage") == [original]

            await repository.mutate(
                "budgets", "budget", {"id": "budget", "limit_micro_usd": 5}, {"id": "put"}
            )
            assert (await repository.get("budgets", "budget"))["limit_micro_usd"] == 5
            assert await repository.list("audit") == [{"id": "put"}]

            await repository.mutate("budgets", "budget", None, {"id": "delete"})
            assert (await repository.get("budgets", "budget"))["_deleted"]
            assert len(await repository.list("audit")) == 2
        finally:
            await table.delete_table()
