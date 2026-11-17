"""Resolve the facts pinned at admission: assignment, hierarchy, price, budgets and bounds."""

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine.assignments import enabled_assignments
from apim_rate_limit_foundry.models import Assignment, Budget, BudgetCheck, Organization, Price
from apim_rate_limit_foundry.models.model_bounds import ModelBounds
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.organization_snapshot import OrganizationSnapshot
from apim_rate_limit_foundry.stores.contracts import Record


class AdmissionResolver:
    """Pure lookups over a configuration snapshot, guided by host settings."""

    def __init__(self, settings: Settings) -> None:
        """Bind the settings holding the model registry and host-wide ceilings."""
        self.settings = settings

    @staticmethod
    def assignment(tenant_id: str, principal_id: str, records: list[Record]) -> Assignment | None:
        """Resolve exactly one enabled tenant/user assignment, otherwise return None."""
        matches = enabled_assignments(records, tenant_id, principal_id)
        if len(matches) != 1:
            return None
        return matches[0]

    @staticmethod
    def organization_context(assignment: Assignment, records: list[Record]) -> OrganizationSnapshot:
        """Validate the enabled parent chain and snapshot team chargeback dimensions."""
        organizations = {record["id"]: Organization.model_validate(record) for record in records}
        team = organizations.get(assignment.team_id)
        department = organizations.get(assignment.department_id)
        if (
            team is None
            or department is None
            or not team.enabled
            or not department.enabled
            or team.kind != "team"
            or department.kind != "department"
            or team.tenant_id != assignment.tenant_id
            or department.tenant_id != assignment.tenant_id
            or team.department_id != department.id
        ):
            raise ValueError("Assigned organization is unavailable")
        return OrganizationSnapshot(
            team_id=team.id,
            department_id=department.id,
            business_unit=team.business_unit,
            cost_center=team.cost_center,
        )

    def deployment(self, check: BudgetCheck) -> ModelDeployment | None:
        """Return the registered deployment, or None when no registry is configured."""
        if not self.settings.model_registry:
            return None
        return self.settings.registered_model(check.api_protocol, check.model)

    def price(self, check: BudgetCheck, records: list[Record]) -> Price:
        """Require one model price, pinned to the registry version when configured."""
        deployment = self.deployment(check)
        version = deployment.price_version if deployment else None
        matches = [
            Price.model_validate(record)
            for record in records
            if record.get("model") == check.model
            and (version is None or record.get("version") == version)
        ]
        if len(matches) != 1:
            raise ValueError("Exactly one matching price card is required")
        return matches[0]

    def model_bounds(self, deployment: ModelDeployment | None) -> ModelBounds:
        """Pin the registered model ceilings, or the host-wide ceilings without a registry."""
        return ModelBounds(
            max_input_tokens=(
                deployment.max_input_tokens if deployment else self.settings.max_input_tokens
            ),
            max_output_tokens=(
                deployment.max_output_tokens if deployment else self.settings.max_output_tokens
            ),
        )

    @staticmethod
    def matching_budgets(
        check: BudgetCheck, assignment: Assignment, records: list[Record]
    ) -> list[Budget]:
        """Select enabled same-tenant user/team/department caps for model or wildcard."""
        return [
            budget
            for record in records
            if (budget := Budget.model_validate(record)).enabled
            and budget.tenant_id == check.tenant_id
            and budget.covers(check.principal_id, assignment.team_id, assignment.department_id)
            and budget.model in ("*", check.model)
        ]
