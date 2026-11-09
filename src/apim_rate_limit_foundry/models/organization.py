from typing import Literal

from pydantic import Field, model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class Organization(Contract):
    id: Identifier
    tenant_id: Identifier
    kind: Literal["team", "department"]
    name: str = Field(min_length=1, max_length=200)
    department_id: Identifier | None = None
    business_unit: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    cost_center: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    enabled: bool = True

    @model_validator(mode="after")
    def validate_parent(self) -> "Organization":
        if self.kind == "team" and not self.department_id:
            raise ValueError("Teams must reference a department")
        if self.kind == "department" and self.department_id is not None:
            raise ValueError("Departments cannot have a parent department")
        return self
