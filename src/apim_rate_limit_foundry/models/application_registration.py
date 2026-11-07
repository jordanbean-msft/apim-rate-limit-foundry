from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import SubscriptionIdentifier


class ApplicationRegistration(Contract):
    tenant_id: SubscriptionIdentifier
    display_name: str = Field(min_length=1, max_length=128)
