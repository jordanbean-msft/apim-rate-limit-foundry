from typing import Literal

from pydantic import BaseModel


class BudgetDecision(BaseModel):
    """Gateway admission result; a monthly denial is still a successful decision."""

    allowed: bool
    request_id: str
    reason: Literal["allowed", "budget_exhausted"]
    denied_budget_ids: list[str]
    reset_at: str
    retry_after: int
