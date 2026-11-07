from typing import Any

from pydantic import Field, model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import (
    ApiProtocol,
    Identifier,
    Service,
    SubscriptionIdentifier,
)
from apim_rate_limit_foundry.models.usage import Usage


class Reserve(Contract):
    request_id: Identifier
    principal_id: Identifier
    tenant_id: Identifier
    subscription_id: SubscriptionIdentifier
    service: Service
    model: Identifier
    operation: Identifier
    usage: Usage
    streaming: bool = False
    price_version: Identifier | None = None
    document_bound_verified: bool = False
    api_protocol: ApiProtocol | None = None
    payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def protocol_matches_service(self) -> "Reserve":
        if self.service != "foundry" and self.api_protocol is not None:
            raise ValueError("API protocols apply only to Foundry requests")
        if self.payload_sha256 and (self.service != "foundry" or not self.streaming):
            raise ValueError("Payload binding applies only to Foundry streams")
        return self

    @property
    def effective_protocol(self) -> ApiProtocol | None:
        return (self.api_protocol or "openai-chat") if self.service == "foundry" else None

    @classmethod
    def from_persisted(cls, value: dict[str, Any]) -> "Reserve":
        """Read legacy user-scoped liabilities without treating them as app admissions."""
        if not value.get("subscription_id"):
            principal_id = value.get("principal_id")
            if not isinstance(principal_id, str):
                raise ValueError("Legacy reservation is missing its actor identity")
            value = {**value, "subscription_id": "legacy-user-v1"}
        return cls.model_validate(value)
