from pydantic import BaseModel


class ChargebackRow(BaseModel):
    """Monthly persisted-history aggregate; unknown requests are counted separately."""

    business_unit: str
    cost_center: str
    department_id: str
    team_id: str
    user_ref: str
    subscription_id: str
    model: str
    month: str
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None = None
    output_tokens: int | None
    cost_micro_usd: int | None
    cost_basis: str | None = None
    unknown_requests: int
