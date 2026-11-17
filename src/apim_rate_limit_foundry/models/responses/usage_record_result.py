from pydantic import BaseModel

from apim_rate_limit_foundry.models.responses.usage_event import UsageEvent


class UsageRecordResult(BaseModel):
    """Redis-accepted usage event and whether it was an identical retry."""

    event: UsageEvent
    replayed: bool
