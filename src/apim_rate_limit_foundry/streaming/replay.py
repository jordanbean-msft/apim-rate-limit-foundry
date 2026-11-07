import logging

from azure.core.exceptions import AzureError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Settle
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.telemetry import emit


async def replay_stream_usage(engine: Engine) -> int:
    """Replay trusted terminal evidence before conservative expiry finalization."""
    completed = 0
    for record in await engine.repository.list("stream_usage"):
        reservation_id = record["id"]
        if await engine.repository.get("settlements", reservation_id):
            continue
        try:
            await engine.settle(
                Settle(
                    reservation_id=reservation_id,
                    status="actual",
                    provider_usage=record["data"]["provider_usage"],
                )
            )
        except (ValueError, Conflict, OSError, AzureError, RedisError) as error:
            subscription_id = record.get("subscription_id")
            application: dict[str, str] = {}
            if subscription_id:
                registration = engine.settings.application_registry.get(subscription_id)
                application = {
                    "subscription_id": subscription_id,
                    "application_name": (
                        registration.display_name if registration else subscription_id
                    ),
                }
            emit(
                "stream_settlement_pending",
                level=logging.WARNING,
                reservation_id=reservation_id,
                error_type=type(error).__name__,
                reason="trusted_usage_replay_failed",
                streaming=True,
                estimated=True,
                **application,
            )
        else:
            completed += 1
    return completed
