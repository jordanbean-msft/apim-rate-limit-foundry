"""Signals for admission decisions, kept apart from the decision logic."""

from apim_rate_limit_foundry.engine.keys import opaque
from apim_rate_limit_foundry.engine.spend import remaining_micro_usd
from apim_rate_limit_foundry.models import BudgetCheck
from apim_rate_limit_foundry.models.admission_context import AdmissionContext
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.telemetry import emit


class AdmissionTelemetry:
    """Emit the events and metrics describing one admission, fresh or replayed."""

    @staticmethod
    def evaluated(check: BudgetCheck, context: AdmissionContext, spend: dict[str, int]) -> None:
        """Emit one evaluation per pinned budget, with its spend read at admission."""
        denied = context.decision.denied_budget_ids
        for budget in context.budgets:
            spent = spend[budget.id]
            rate_metrics.budget(
                budget.subject_type,
                budget.model,
                spent,
                budget.limit_micro_usd,
                budget.id in denied,
                "admission",
            )
            emit(
                "budget_evaluated",
                budget_id=budget.id,
                budget_model=budget.model,
                subject_type=budget.subject_type,
                month=context.month,
                limit_micro_usd=budget.limit_micro_usd,
                spent_micro_usd=spent,
                remaining_micro_usd=remaining_micro_usd(budget.limit_micro_usd, spent),
                allowed=budget.id not in denied,
                reason="budget_exhausted" if budget.id in denied else "within_budget",
                reset_at=context.decision.reset_at,
                user_ref=opaque(check.tenant_id, check.principal_id),
                team_id=context.organization.team_id,
                department_id=context.organization.department_id,
            )

    @staticmethod
    def decided(check: BudgetCheck, context: AdmissionContext, replayed: bool) -> None:
        """Emit the budget_decision summary and count the decision.

        A fresh decision also lists the budgets it evaluated; a replay returns the
        pinned decision and does not reevaluate any budget.
        """
        decision = context.decision
        budget_ids = None if replayed else [budget.id for budget in context.budgets]
        emit(
            "budget_decision",
            allowed=decision.allowed,
            reason=decision.reason,
            model=check.model,
            user_ref=opaque(check.tenant_id, check.principal_id),
            team_id=context.organization.team_id,
            department_id=context.organization.department_id,
            denied_budget_ids=decision.denied_budget_ids,
            budget_ids=budget_ids,
            budget_count=None if budget_ids is None else len(budget_ids),
            denied_budget_count=len(decision.denied_budget_ids),
            month=context.month,
            price_version=context.price_version,
            reset_at=decision.reset_at,
            retry_after=decision.retry_after,
            replayed=replayed,
        )
        rate_metrics.decision(
            check.model, check.api_protocol, check.streaming, decision.allowed, replayed
        )
