from datetime import datetime
from typing import Literal

from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import ApiProtocol, Service


class UsageSummary(Contract):
    id: str
    tenant_id: str
    principal_id: str
    service: Service
    model: str
    period: Literal["hour", "day"]
    start_at: datetime
    end_at: datetime
    request_count: int = 0
    admitted_requests: int = 0
    denied_requests: int = 0
    estimated_requests: int = Field(
        default=0,
        description="Admitted requests with conservative units or uncertain cached-input usage.",
    )
    cost_micro_usd: int = Field(
        default=0,
        description="One canonical charge per admitted request, never summed across budget rules.",
    )
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    pages: int = 0
    text_records: int = 0
    api_protocol: ApiProtocol | None = None
    cache_write_input_tokens_5m: int = 0
    cache_write_input_tokens_1h: int = 0
