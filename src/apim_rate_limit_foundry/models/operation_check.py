from uuid import UUID

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier, SubscriptionIdentifier


class OperationCheck(Contract):
    operation_id: UUID
    principal_id: Identifier
    tenant_id: Identifier
    subscription_id: SubscriptionIdentifier
    model: Identifier
