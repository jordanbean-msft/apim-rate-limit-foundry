"""Publish usage events to Event Hubs with the Function's managed identity."""

import json
import logging

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Record
from apim_rate_limit_foundry.telemetry import dependency_span, emit


class EventHubUsagePublisher:
    """Send each event to a partition keyed by its tenant and user reference.

    Success means the broker accepted the batch, not that a consumer processed it.
    """

    def __init__(self, settings: Settings, credential: AsyncTokenCredential) -> None:
        """Create a producer for the configured namespace and hub."""
        self.server_address = settings.event_hub_fqdn
        self.destination = settings.event_hub_name
        self.producer = EventHubProducerClient(
            fully_qualified_namespace=settings.event_hub_fqdn,
            eventhub_name=settings.event_hub_name,
            credential=ObservedCredential(credential),
        )

    async def publish(self, usage_event: Record) -> None:
        """Send with SDK transport retries; log/count handled failures without requeueing."""
        identifiers: Record = {
            "request_id": usage_event.get("request_id"),
            "event_id": usage_event.get("event_id"),
        }
        partition_key = f"{usage_event['tenant_ref']}:{usage_event['user_ref']}"
        try:
            with dependency_span(
                "event-hub",
                "send",
                server_address=self.server_address,
                destination=self.destination,
            ):
                batch = await self.producer.create_batch(partition_key=partition_key)
                batch.add(EventData(json.dumps(usage_event, separators=(",", ":"))))
                await self.producer.send_batch(batch)
        except (AzureError, OSError, ValueError) as error:
            emit(
                "usage_event_publish_failed",
                level=logging.WARNING,
                error_type=type(error).__name__,
                **identifiers,
            )
            rate_metrics.event_publish("failed")
            return
        emit("usage_event_publish_accepted", status="accepted", **identifiers)
        rate_metrics.event_publish("accepted")

    async def close(self) -> None:
        """Close the producer connection."""
        await self.producer.close()
