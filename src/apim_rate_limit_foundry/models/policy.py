from typing import Literal

from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Amount, Identifier, Service


class Policy(Contract):
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    tenant_id: Identifier = "*"
    subscription_id: Identifier
    service: Service
    model: Identifier = "*"
    limit: Amount
    period: Literal["minute", "hour", "day", "month"]
    metric: Literal["cost", "tokens", "requests", "pages", "text_records"]
    enabled: bool = True
    priority: int = 0
