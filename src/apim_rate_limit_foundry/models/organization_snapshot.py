from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class OrganizationSnapshot(Contract):
    """Team and department chargeback dimensions captured when a request was admitted."""

    team_id: Identifier
    department_id: Identifier
    business_unit: str
    cost_center: str
