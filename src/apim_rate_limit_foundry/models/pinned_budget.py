from typing import Literal

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class PinnedBudget(Contract):
    """A cap a request was admitted under, with the Redis counter key holding its spend."""

    id: Identifier
    subject_type: Literal["user", "team", "department"]
    subject_id: Identifier
    model: Identifier
    limit_micro_usd: int
    counter_key: str
