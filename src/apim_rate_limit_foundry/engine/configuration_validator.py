"""Cross-record hierarchy rules enforced before configuration is written."""

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
        for existing in await self.reader.configuration("assignments"):
            if existing.get("id") != assignment.id and (
                existing.get("tenant_id") == assignment.tenant_id
                and existing.get("principal_id") == assignment.principal_id
                and existing.get("enabled") is True
                and assignment.enabled
            ):
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
        parent = await self.repository.get("organizations", organization.department_id or "")
        if (
            parent is None
            or parent.get("_deleted")
            or parent.get("kind") != "department"
            or parent.get("enabled") is not True
            or parent.get("tenant_id") != organization.tenant_id
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
        return any(
            row.get("tenant_id") == budget.tenant_id
            and row.get("principal_id") == budget.subject_id
            and row.get("enabled") is True
            for row in await self.reader.configuration("assignments")
        )

    async def _has_active_unit(self, budget: Budget) -> bool:
        organization = await self.repository.get("organizations", budget.subject_id)
        expected_kind = "team" if budget.subject_type == "team" else "department"
        return bool(
            organization
            and not organization.get("_deleted")
            and organization.get("kind") == expected_kind
            and organization.get("tenant_id") == budget.tenant_id
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
