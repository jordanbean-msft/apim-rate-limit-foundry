"""Read live monthly spend for budgets and derive their remaining balance."""

from apim_rate_limit_foundry.engine.keys import budget_counter_key
from apim_rate_limit_foundry.models import Budget
from apim_rate_limit_foundry.stores.contracts import CounterStore


async def read_spend(counters: CounterStore, budgets: list[Budget], month: str) -> dict[str, int]:
    """Read current-month spend in micro-USD for each budget, keyed by budget ID."""
    keys = {budget.id: budget_counter_key(budget, month) for budget in budgets}
    totals = await counters.totals(month, list(keys.values()))
    return {budget_id: totals[key] for budget_id, key in keys.items()}


def remaining_micro_usd(limit: int, spent: int) -> int:
    """Balance left under a soft cap, never negative even when spend overshoots."""
    return max(0, limit - spent)
