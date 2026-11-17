from typing import Literal

from pydantic import BaseModel

from apim_rate_limit_foundry.models.types import ApiProtocol


class UsageEvent(BaseModel):
    """Finalized usage-v2 event; unknown provider usage keeps null counts, never zero."""

    event_version: Literal[2]
    event_name: Literal["usage_recorded"]
    event_id: str
    request_id: str
    timestamp: str
    month: str
    tenant_ref: str
    user_ref: str
    team_id: str
    department_id: str
    business_unit: str
    cost_center: str
    subscription_id: str
    model: str
    api_protocol: ApiProtocol
    streaming: bool
    status: Literal["actual", "usage_unknown"]
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None = None
    output_tokens: int | None
    cost_micro_usd: int | None
    cost_basis: Literal["provider_usage", "estimated_upper_bound"] | None = None
    out_of_bounds: bool | None = None
    price_version: str
