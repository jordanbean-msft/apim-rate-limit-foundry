from typing import Literal

from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import SAFE_NAME, Identifier


class Budget(Contract):
    """UTC-month spending cap for one user, team or department.

    model="*" aggregates all models; a named alias caps only that model. Limits
    are integer micro-USD (1 USD = 1,000,000 micro-USD), not floating-point dollars.
    Zero is an immediate cap. Admission does not reserve the next call's cost, so
    actual usage and concurrent in-flight calls can take spend above the limit.
    """

    id: Identifier
    tenant_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    subject_type: Literal["user", "team", "department"]
    subject_id: Identifier
    model: str = Field(
        default="*",
        pattern=rf"^(\*|{SAFE_NAME})$",
    )
    limit_micro_usd: int = Field(strict=True, ge=0, le=9_000_000_000_000)
    enabled: bool = True

    def covers(self, principal_id: str, team_id: str, department_id: str) -> bool:
        """Whether this cap's subject is the user, team or department of an assignment."""
        return (self.subject_type, self.subject_id) in {
            ("user", principal_id),
            ("team", team_id),
            ("department", department_id),
        }
