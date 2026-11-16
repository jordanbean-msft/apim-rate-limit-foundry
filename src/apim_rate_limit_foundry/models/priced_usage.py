from typing import Literal

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.usage_counts import UsageCounts

CostBasis = Literal["provider_usage", "estimated_upper_bound"]
UsageReason = Literal[
    "provider_usage", "provider_usage_missing", "provider_usage_invalid", "reported_unknown"
]


class PricedUsage(Contract):
    """Outcome of pricing one finalized request.

    Provider usage is priced from real counts. Missing, invalid or unreported usage
    stays status ``usage_unknown`` with no counts, but is still charged a
    conservative upper bound so budgets decrement. ``out_of_bounds`` flags real
    counts above the model bounds pinned at admission; they are still charged.
    """

    status: Literal["actual", "usage_unknown"]
    reason: UsageReason
    counts: UsageCounts | None
    cost_micro_usd: int
    cost_basis: CostBasis
    out_of_bounds: bool = False
