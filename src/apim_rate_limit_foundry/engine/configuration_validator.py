"""Cross-record hierarchy rules enforced before configuration is written."""

from apim_rate_limit_foundry.engine.assignments import enabled_assignments
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.models import Assignment, Budget, Organization
from apim_rate_limit_foundry.stores.contracts import Repository


class ConfigurationValidator:
    """Check that assignments, organizations and budgets reference active parents."""

    def __init__(self, repository: Repository, reader: ConfigurationReader) -> None:
        """Bind the durable store and configuration reader."""
        self.repository = repository
        self.reader = reader

    async def validate_assignment(self, assignment: Assignment) -> None:
        """Require one active user assignment and an enabled same-tenant parent chain."""
        existing = enabled_assignments(
            await self.reader.configuration("assignments"),
            assignment.tenant_id,
            assignment.principal_id,
        )
        if assignment.enabled and any(item.id != assignment.id for item in existing):
            raise ValueError("An active assignment already exists for this user")
        organizations = [
            Organization.model_validate(r) for r in await self.reader.configuration("organizations")
        ]
        team = self._unit(organizations, assignment.team_id, "team", assignment.tenant_id)
        department = self._unit(
            organizations, assignment.department_id, "department", assignment.tenant_id
        )
        if team is None or department is None or team.department_id != department.id:
            raise ValueError("Assignment requires an enabled team and its enabled department")

    async def validate_organization(self, organization: Organization) -> None:
        """Require a team's parent to be an enabled department in the same tenant."""
        if organization.kind != "team":
            return
        if not await self._is_active_unit(
            organization.department_id or "", "department", organization.tenant_id
        ):
            raise ValueError("Team parent must be an enabled department in the same tenant")

    async def validate_budget(self, budget: Budget) -> None:
        """Reject budget subjects without an active matching user or organization."""
        if budget.subject_type == "user":
            valid = await self._has_active_user(budget)
        else:
            valid = await self._has_active_unit(budget)
        if not valid:
            raise ValueError("Budget subject must be an active user or organization unit")

    async def _has_active_user(self, budget: Budget) -> bool:
        return bool(
            enabled_assignments(
                await self.reader.configuration("assignments"), budget.tenant_id, budget.subject_id
            )
        )

    async def _has_active_unit(self, budget: Budget) -> bool:
        return await self._is_active_unit(budget.subject_id, budget.subject_type, budget.tenant_id)

    async def _is_active_unit(self, unit_id: str, kind: str, tenant_id: str) -> bool:
        """Whether a stored organization is live, of this kind, enabled and in the tenant."""
        organization = await self.repository.get("organizations", unit_id)
        return bool(
            organization
            and not organization.get("_deleted")
            and organization.get("kind") == kind
            and organization.get("tenant_id") == tenant_id
            and organization.get("enabled") is True
        )

    @staticmethod
    def _unit(
        organizations: list[Organization], unit_id: str, kind: str, tenant_id: str
    ) -> Organization | None:
        """Find an enabled organization unit of one kind within the tenant."""
        return next(
            (
                item
                for item in organizations
                if item.id == unit_id
                and item.kind == kind
                and item.tenant_id == tenant_id
                and item.enabled
            ),
            None,
        )
