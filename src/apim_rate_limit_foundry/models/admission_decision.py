from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class AdmissionDecision(Contract):
    """The allow or deny outcome pinned for one request ID, without the request ID itself."""

    allowed: bool
    reason: str
    denied_budget_ids: list[Identifier]
    reset_at: str
    retry_after: int
