from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class Assignment(Contract):
    id: Identifier
    tenant_id: Identifier
    principal_id: Identifier
    team_id: Identifier
    department_id: Identifier
    display_label: str | None = Field(default=None, max_length=128)
    enabled: bool = True
