"""Surface budget balances after accepted usage, using the caps pinned at admission."""

import logging

from azure.core.exceptions import AzureError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.engine.budget_events import emit_budget_status
from apim_rate_limit_foundry.engine.keys import budget_counter_key
from apim_rate_limit_foundry.models import Budget
from apim_rate_limit_foundry.models.admission_context import AdmissionContext
from apim_rate_limit_foundry.models.pinned_budget import PinnedBudget
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import CounterStore
from apim_rate_limit_foundry.telemetry import emit


class BudgetStatusReporter:
    """Emit ``budget_status`` telemetry from the live Redis balance of each pinned cap."""

    def __init__(self, counters: CounterStore) -> None:
        """Bind the operational store holding monthly spend."""
        self.counters = counters

    @staticmethod
    def pin(budgets: list[Budget], month: str) -> list[PinnedBudget]:
        """Snapshot the caps a request was admitted under, with their spend counter keys."""
        return [
            PinnedBudget(
                id=budget.id,
                subject_type=budget.subject_type,
                subject_id=budget.subject_id,
                model=budget.model,
                limit_micro_usd=budget.limit_micro_usd,
                counter_key=budget_counter_key(budget, month),
            )
            for budget in budgets
        ]

    async def report(self, context: AdmissionContext) -> None:
        """Emit one status event and utilization metric per cap pinned at admission.

        The usage is already accepted, so a Redis failure here is logged and not
        propagated.
        """
        if not context.budgets:
            return
        keys = [budget.counter_key for budget in context.budgets]
        try:
            totals = await self.counters.totals(context.month, keys)
        except (OSError, AzureError, RedisError):
            emit("limiter_dependency_unavailable", level=logging.WARNING, operation="budget_status")
            return
        for budget in context.budgets:
            spent = totals[budget.counter_key]
            emit_budget_status(
                tenant_id=context.check.tenant_id,
                month=context.month,
                budget_id=budget.id,
                subject_type=budget.subject_type,
                subject_id=budget.subject_id,
                model=budget.model,
                limit_micro_usd=budget.limit_micro_usd,
                spent_micro_usd=spent,
                team_id=context.organization.team_id,
                department_id=context.organization.department_id,
            )
            rate_metrics.budget(
                budget.subject_type, budget.model, spent, budget.limit_micro_usd, False, "usage"
            )
