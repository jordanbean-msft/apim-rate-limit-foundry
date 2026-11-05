import os
from uuid import uuid4

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Settle, Usage
from apim_rate_limit_foundry.runtime import Runtime


@pytest.mark.skipif(
    not os.environ.get("TEST_REDIS_URL") or not os.environ.get("TEST_TABLE_CONNECTION_STRING"),
    reason="Set TEST_REDIS_URL and TEST_TABLE_CONNECTION_STRING for Redis+Azurite integration",
)
async def test_redis_and_azurite_durable_recovery(
    request_body: Reserve,
    price: Price,
    policy: Policy,
) -> None:
    settings = Settings(
        _env_file=None,
        local_store_enabled=True,
        local_redis_url=os.environ["TEST_REDIS_URL"],
        local_table_connection_string=os.environ["TEST_TABLE_CONNECTION_STRING"],
        table_name=f"Test{uuid4().hex}",
    )
    runtime = Runtime(settings)
    counters, repository = runtime.engine.counters, runtime.engine.repository
    counters.key = f"{{limiter-azurite-{uuid4().hex}}}:ledger"
    client = await counters.connection()
    try:
        await repository.client.create_table()
        await repository.create("policies", policy.id, policy.model_dump(mode="json"))
        await repository.create("prices", price.id, price.model_dump(mode="json"))
        await runtime.engine.recover()
        decision = await runtime.engine.reserve(request_body)
        assert decision.allowed
        await runtime.engine.settle(
            Settle(
                reservation_id=decision.reservation_id,
                status="actual",
                usage=Usage(input_tokens=2, output_tokens=1),
            )
        )
        await client.delete(counters.key)
        await runtime.engine.recover()
        assert (await runtime.engine.reserve(request_body)).allowed
        records = await repository.list("settlements")
        assert len(records) == 1
        assert records[0]["data"]["debits"][0]["amount"] == 8
        await repository.mutate(
            "policies",
            policy.id,
            None,
            {
                "id": uuid4().hex,
                "tenant_id": "tenant-1",
                "principal_id": "admin",
                "kind": "configuration",
                "data": {"action": "delete"},
            },
        )
        assert await runtime.engine.configuration("policies") == []
        assert len(await repository.list("audit")) == 3
    finally:
        await client.delete(counters.key)
        await repository.client.delete_table()
        await runtime.close()
