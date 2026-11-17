import json
from unittest.mock import AsyncMock, Mock

import pytest
from azure.core.exceptions import AzureError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.export.event_hub_usage_publisher import EventHubUsagePublisher

EVENT = {
    "event_id": "event-1",
    "request_id": "request-1",
    "tenant_ref": "tenant-ref",
    "user_ref": "user-ref",
}


@pytest.fixture
def producer(monkeypatch: pytest.MonkeyPatch) -> Mock:
    client = Mock()
    client.create_batch = AsyncMock()
    client.send_batch = AsyncMock()
    client.close = AsyncMock()
    monkeypatch.setattr(
        "apim_rate_limit_foundry.export.event_hub_usage_publisher.EventHubProducerClient",
        Mock(return_value=client),
    )
    return client


def make_publisher() -> EventHubUsagePublisher:
    settings = Settings(
        _env_file=None,
        local_store_enabled=True,
        event_hub_fqdn="events.servicebus.windows.net",
        event_hub_name="usage",
    )
    return EventHubUsagePublisher(settings, AsyncMock())


async def test_event_is_sent_once_with_the_user_partition_key(producer: Mock) -> None:
    batch = Mock()
    producer.create_batch.return_value = batch

    await make_publisher().publish(EVENT)

    producer.create_batch.assert_awaited_once_with(partition_key="tenant-ref:user-ref")
    assert json.loads(batch.add.call_args.args[0].body_as_str()) == EVENT
    producer.send_batch.assert_awaited_once_with(batch)


@pytest.mark.parametrize("failure", [AzureError("unavailable"), ValueError("too large")])
async def test_delivery_failures_are_swallowed_not_retried(
    producer: Mock, failure: Exception
) -> None:
    producer.create_batch.return_value = Mock(add=Mock(side_effect=failure))

    await make_publisher().publish(EVENT)

    producer.send_batch.assert_not_awaited()


async def test_close_releases_the_producer(producer: Mock) -> None:
    await make_publisher().close()

    producer.close.assert_awaited_once()
