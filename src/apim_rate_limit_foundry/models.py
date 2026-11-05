from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:@*-]+$")]
Service = Literal["foundry", "document-intelligence", "language"]
Amount = Annotated[int, Field(strict=True, ge=0, le=9_000_000_000_000)]


def _decimal_string(value: object) -> object:
    if not isinstance(value, str | Decimal):
        raise ValueError("Prices must be decimal USD strings, never floats")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    Field(ge=0, le=1_000_000, allow_inf_nan=False),
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Usage(Contract):
    input_tokens: Amount = 0
    output_tokens: Amount = 0
    cached_input_tokens: Amount = 0
    pages: Amount = 0
    text_records: Amount = 0
    requests: Amount = 1

    @model_validator(mode="after")
    def cached_subset(self) -> "Usage":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Cached tokens must be a subset of input tokens")
        return self


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


class Settle(Contract):
    reservation_id: Identifier
    usage: Usage
    status: Literal["actual", "conservative"]


class Release(Contract):
    reservation_id: Identifier


class Policy(Contract):
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    tenant_id: Identifier = "*"
    service: Service
    model: Identifier = "*"
    principal_id: Identifier = "*"
    limit: Amount
    period: Literal["minute", "hour", "day", "month"]
    metric: Literal["cost", "tokens", "requests", "pages", "text_records"]
    enabled: bool = True
    priority: int = 0


class Price(Contract):
    id: Identifier
    service: Service
    model: Identifier
    version: Identifier
    input_per_million: Money | None = None
    output_per_million: Money | None = None
    cached_input_per_million: Money | None = None
    per_page: Money | None = None
    per_text_record: Money | None = None
    per_request: Money | None = None


class Assignment(Contract):
    id: Identifier
    tenant_id: Identifier
    principal_id: Identifier
    policy_ids: list[Identifier]


class Decision(Contract):
    allowed: bool
    reservation_id: str | None = None
    reason: str
    remaining: int = 0
    retry_after: int = 0
    reset_at: str
    estimated: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
