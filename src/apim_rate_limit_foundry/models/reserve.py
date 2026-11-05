from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier, Service
from apim_rate_limit_foundry.models.usage import Usage


class Reserve(Contract):
    request_id: Identifier
    principal_id: Identifier
    tenant_id: Identifier
    subscription_id: Identifier | None = None
    service: Service
    model: Identifier
    operation: Identifier
    usage: Usage
    streaming: bool = False
    price_version: Identifier | None = None
    document_bound_verified: bool = False
