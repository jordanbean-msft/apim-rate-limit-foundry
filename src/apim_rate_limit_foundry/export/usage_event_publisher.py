"""Contract for publishing one finalized usage event."""

from typing import Protocol

from apim_rate_limit_foundry.stores.contracts import Record


class UsageEventPublisher(Protocol):
    """Send accepted usage events downstream without affecting Redis accounting.

    Implementations report transport acceptance only, never consumer processing,
    and must not raise for ordinary delivery failures: callers do not retry.
    """

    async def publish(self, usage_event: Record) -> None:
        """Send one versioned usage event, logging rather than raising on failure."""
        ...

    async def close(self) -> None:
        """Release transport resources."""
        ...
