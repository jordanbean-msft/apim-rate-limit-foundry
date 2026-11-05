from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class Assignment(Contract):
    id: Identifier
    tenant_id: Identifier
    principal_id: Identifier
    policy_ids: list[Identifier]
