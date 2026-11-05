from pydantic import model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import ApiProtocol, Identifier, Service
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
    api_protocol: ApiProtocol | None = None

    @model_validator(mode="after")
    def protocol_matches_service(self) -> "Reserve":
        if self.service != "foundry" and self.api_protocol is not None:
            raise ValueError("API protocols apply only to Foundry requests")
        return self

    @property
    def effective_protocol(self) -> ApiProtocol | None:
        return (self.api_protocol or "openai-chat") if self.service == "foundry" else None
