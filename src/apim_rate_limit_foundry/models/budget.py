from typing import Literal

from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class Budget(Contract):
    id: Identifier
    tenant_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    subject_type: Literal["user", "team", "department"]
    subject_id: Identifier
    model: str = Field(
        default="*",
        pattern=r"^(\*|[A-Za-z0-9][A-Za-z0-9._-]{0,127})$",
    )
    limit_micro_usd: int = Field(strict=True, ge=0, le=9_000_000_000_000)
    enabled: bool = True
