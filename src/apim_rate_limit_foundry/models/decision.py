from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract


class Decision(Contract):
    allowed: bool
    reservation_id: str | None = None
    reason: str
    remaining: int = Field(
        default=0,
        description="Minimum numeric remainder across policies; mixed metrics are not comparable. "
        "Use remaining_by_policy for each policy's units.",
    )
    retry_after: int = 0
    reset_at: str
    estimated: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    matched_policy_ids: list[str] = Field(default_factory=list)
    denied_policy_ids: list[str] = Field(default_factory=list)
    remaining_by_policy: dict[str, int] = Field(
        default_factory=dict,
        description="Each value uses that policy's metric; costs are integer micro-USD.",
    )
