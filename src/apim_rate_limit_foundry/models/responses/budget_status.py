from typing import Literal

from pydantic import BaseModel


class BudgetStatus(BaseModel):
    """Live Redis monthly spend for one cap; remaining is clamped at zero."""

    budget_id: str
    name: str
    subject_type: Literal["user", "team", "department"]
    subject_id: str
    model: str
    limit_micro_usd: int
    spent_micro_usd: int
    remaining_micro_usd: int
    month: str
