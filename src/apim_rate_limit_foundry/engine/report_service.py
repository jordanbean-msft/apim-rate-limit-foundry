"""Serve usage history, budget status and chargeback reports."""

from apim_rate_limit_foundry.accounting import usage_partition, utc_month
from apim_rate_limit_foundry.engine.assignments import enabled_assignments
from apim_rate_limit_foundry.engine.budget_events import emit_budget_status
from apim_rate_limit_foundry.engine.catalog import USAGE_COLLECTION
from apim_rate_limit_foundry.engine.chargeback_aggregator import ChargebackAggregator
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.spend import read_spend, remaining_micro_usd
from apim_rate_limit_foundry.models import Assignment, Budget
from apim_rate_limit_foundry.stores.contracts import CounterStore, Record, Repository


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
        """Combine visible caps with live Redis current-month spend.

        Admins see all enabled tenant caps; users see their assigned hierarchy.
        Caps and hierarchy come from the shared configuration snapshot, so this
        read touches Redis only. It may differ from durable chargeback history
        and does not reconstruct lost operational counters from Table.
        """
        configuration = await self.reader.snapshot()
        assignments = enabled_assignments(
            configuration["assignments"], tenant_id, None if admin else principal_id
        )
        if not admin and not assignments:
            return []
        month, _ = utc_month()
        budgets = self._visible_budgets(tenant_id, assignments, admin, configuration["budgets"])
        spend = await read_spend(self.counters, budgets, month)
        departments = {
            organization["id"]: organization.get("department_id")
            for organization in configuration["organizations"]
        }
        result = []
        for budget in budgets:
            row = self._row(budget, spend[budget.id], month)
            result.append(row)
            self._emit_status(tenant_id, budget, row, assignments, departments)
        return result

    def _visible_budgets(
        self, tenant_id: str, assignments: list[Assignment], admin: bool, records: list[Record]
    ) -> list[Budget]:
        """Select enabled tenant budgets, limited to the caller's hierarchy unless admin."""
        return [
            budget
            for record in records
            if (budget := Budget.model_validate(record)).enabled
            and budget.tenant_id == tenant_id
            and (admin or any(self._covers(budget, item) for item in assignments))
        ]

    @staticmethod
    def _covers(budget: Budget, assignment: Assignment) -> bool:
        """Whether the budget's subject is the assignment's user, team or department."""
        return budget.covers(assignment.principal_id, assignment.team_id, assignment.department_id)

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
            "remaining_micro_usd": remaining_micro_usd(budget.limit_micro_usd, actual),
            "month": month,
        }

    def _hierarchy(
        self, budget: Budget, assignments: list[Assignment], departments: dict[str, str | None]
    ) -> tuple[str | None, str | None]:
        """Resolve the team and department a budget's telemetry should be attributed to.

        A team cap with no covering assignment takes its department from the
        organization snapshot rather than a per-budget Table lookup.
        """
        assignment = next((item for item in assignments if self._covers(budget, item)), None)
        team_id = budget.subject_id if budget.subject_type == "team" else None
        department_id = budget.subject_id if budget.subject_type == "department" else None
        if assignment is not None:
            team_id = team_id or assignment.team_id
            department_id = department_id or assignment.department_id
        elif team_id is not None:
            department_id = departments.get(team_id)
        return team_id, department_id

    def _emit_status(
        self,
        tenant_id: str,
        budget: Budget,
        row: Record,
        assignments: list[Assignment],
        departments: dict[str, str | None],
    ) -> None:
        """Emit one budget_status event with opaque user references."""
        team_id, department_id = self._hierarchy(budget, assignments, departments)
        emit_budget_status(
            tenant_id=tenant_id,
            month=row["month"],
            budget_id=budget.id,
            subject_type=budget.subject_type,
            subject_id=budget.subject_id,
            model=budget.model,
            limit_micro_usd=budget.limit_micro_usd,
            spent_micro_usd=row["spent_micro_usd"],
            team_id=team_id,
            department_id=department_id,
        )
