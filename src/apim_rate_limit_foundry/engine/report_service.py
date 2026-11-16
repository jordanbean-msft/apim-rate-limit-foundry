"""Serve usage history, budget status and chargeback reports."""

from apim_rate_limit_foundry.accounting import usage_partition, utc_month
from apim_rate_limit_foundry.engine.catalog import USAGE_COLLECTION
from apim_rate_limit_foundry.engine.chargeback_aggregator import ChargebackAggregator
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.keys import budget_counter_key, opaque
from apim_rate_limit_foundry.models import Assignment, Budget
from apim_rate_limit_foundry.stores.contracts import CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import emit


class ReportService:
    """Read-only views over durable history and live Redis spend."""

    def __init__(
        self,
        repository: Repository,
        counters: CounterStore,
        reader: ConfigurationReader,
        aggregator: ChargebackAggregator,
    ) -> None:
        """Bind stores, the configuration reader and the chargeback aggregator."""
        self.repository = repository
        self.counters = counters
        self.reader = reader
        self.aggregator = aggregator

    async def usage(
        self, tenant_id: str, principal_id: str, admin: bool, month: str | None = None
    ) -> list[Record]:
        """Return eventually persisted events for one UTC month (default: current).

        Scoped to a tenant and, unless admin, user. Reads one Table partition keyed
        by tenant and month. Accepted Redis-only events may be delayed or absent.
        """
        records = await self.repository.list(
            USAGE_COLLECTION, usage_partition(tenant_id, month or utc_month()[0])
        )
        return [
            record["data"]["event"]
            for record in records
            if admin or record.get("principal_id") == principal_id
        ]

    async def chargeback(
        self, tenant_id: str, month: str, principal_id: str | None
    ) -> list[Record]:
        """Aggregate durable monthly events by their original chargeback dimensions.

        Reads one Table partition for the tenant and month; an optional principal
        filter narrows it. Results reflect only successfully mirrored events, not
        guaranteed billing completeness.
        """
        records = await self.repository.list(USAGE_COLLECTION, usage_partition(tenant_id, month))
        return self.aggregator.aggregate(records, principal_id)

    async def budget_status(
        self, tenant_id: str, principal_id: str, admin: bool = False
    ) -> list[Record]:
        """Combine durable visible caps with live Redis current-month spend.

        Admins see all enabled tenant caps; users see their assigned hierarchy.
        This report may differ from durable chargeback history and does not
        reconstruct lost operational counters from Table.
        """
        assignments = await self._assignments(tenant_id, principal_id, admin)
        if not admin and not assignments:
            return []
        month, _ = utc_month()
        budgets = await self._visible_budgets(tenant_id, assignments, admin)
        keys = {budget.id: budget_counter_key(budget, month) for budget in budgets}
        totals = await self.counters.totals(month, list(keys.values()))
        result = []
        for budget in budgets:
            row = self._row(budget, totals[keys[budget.id]], month)
            result.append(row)
            await self._emit_status(tenant_id, budget, row, assignments)
        return result

    async def _assignments(
        self, tenant_id: str, principal_id: str, admin: bool
    ) -> list[Assignment]:
        """Select enabled tenant assignments, narrowed to the caller unless admin."""
        return [
            Assignment.model_validate(record)
            for record in await self.reader.configuration("assignments")
            if record.get("tenant_id") == tenant_id
            and record.get("enabled") is True
            and (admin or record.get("principal_id") == principal_id)
        ]

    async def _visible_budgets(
        self, tenant_id: str, assignments: list[Assignment], admin: bool
    ) -> list[Budget]:
        """Select enabled tenant budgets, limited to the caller's hierarchy unless admin."""
        return [
            budget
            for record in await self.reader.configuration("budgets")
            if (budget := Budget.model_validate(record)).enabled
            and budget.tenant_id == tenant_id
            and (admin or any(self._covers(budget, item) for item in assignments))
        ]

    @staticmethod
    def _covers(budget: Budget, assignment: Assignment) -> bool:
        """Whether the budget's subject is the assignment's user, team or department."""
        return (
            (budget.subject_type == "user" and assignment.principal_id == budget.subject_id)
            or (budget.subject_type == "team" and assignment.team_id == budget.subject_id)
            or (
                budget.subject_type == "department"
                and assignment.department_id == budget.subject_id
            )
        )

    @staticmethod
    def _row(budget: Budget, actual: int, month: str) -> Record:
        return {
            "budget_id": budget.id,
            "name": budget.name,
            "subject_type": budget.subject_type,
            "subject_id": budget.subject_id,
            "model": budget.model,
            "limit_micro_usd": budget.limit_micro_usd,
            "spent_micro_usd": actual,
            "remaining_micro_usd": max(0, budget.limit_micro_usd - actual),
            "month": month,
        }

    async def _hierarchy(
        self, budget: Budget, assignments: list[Assignment]
    ) -> tuple[str | None, str | None]:
        """Resolve the team and department a budget's telemetry should be attributed to."""
        assignment = next((item for item in assignments if self._covers(budget, item)), None)
        team_id = (
            budget.subject_id
            if budget.subject_type == "team"
            else assignment.team_id
            if assignment
            else None
        )
        department_id = (
            budget.subject_id
            if budget.subject_type == "department"
            else assignment.department_id
            if assignment
            else None
        )
        if budget.subject_type == "team" and assignment is None:
            team = await self.repository.get("organizations", budget.subject_id)
            if team and not team.get("_deleted"):
                department_id = team.get("department_id")
        return team_id, department_id

    async def _emit_status(
        self, tenant_id: str, budget: Budget, row: Record, assignments: list[Assignment]
    ) -> None:
        """Emit one budget_status event with opaque user references."""
        team_id, department_id = await self._hierarchy(budget, assignments)
        is_user = budget.subject_type == "user"
        emit(
            "budget_status",
            month=row["month"],
            budget_id=budget.id,
            subject_type=budget.subject_type,
            subject_id=opaque(tenant_id, budget.subject_id) if is_user else budget.subject_id,
            model=budget.model,
            limit_micro_usd=budget.limit_micro_usd,
            spent_micro_usd=row["spent_micro_usd"],
            remaining_micro_usd=row["remaining_micro_usd"],
            user_ref=opaque(tenant_id, budget.subject_id) if is_user else None,
            team_id=team_id,
            department_id=department_id,
        )
