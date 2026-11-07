from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier, SubscriptionIdentifier


class Assignment(Contract):
    id: Identifier
    tenant_id: Identifier
    subscription_id: SubscriptionIdentifier
    policy_ids: list[Identifier]
    reader_principal_ids: list[SubscriptionIdentifier] = Field(default_factory=list)
    display_label: str | None = Field(default=None, max_length=128)
