from pydantic import Field

from apim_rate_limit_foundry.models.admission_decision import AdmissionDecision
from apim_rate_limit_foundry.models.assignment import Assignment
from apim_rate_limit_foundry.models.budget_check import BudgetCheck
from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.model_bounds import ModelBounds
from apim_rate_limit_foundry.models.organization_snapshot import OrganizationSnapshot
from apim_rate_limit_foundry.models.pinned_budget import PinnedBudget
from apim_rate_limit_foundry.models.price import Price


class AdmissionContext(Contract):
    """Everything later accounting needs, captured once when a request ID is admitted.

    Reassignment, price edits or a month rollover cannot change this request's
    attribution because the facts are pinned here. It is stored in Redis as the
    ``data`` of the request record and validated again on every later read.
    """

    fingerprint: str
    check: BudgetCheck
    assignment: Assignment
    organization: OrganizationSnapshot
    price: Price
    price_version: str
    model_bounds: ModelBounds
    month: str
    budgets: list[PinnedBudget] = Field(default_factory=list)
    decision: AdmissionDecision
