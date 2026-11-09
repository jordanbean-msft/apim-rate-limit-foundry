from typing import Literal

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class BudgetCheck(Contract):
    request_id: Identifier
    tenant_id: Identifier
    principal_id: Identifier
    subscription_id: Identifier
    model: Identifier
    api_protocol: Literal["openai-chat", "openai-responses"]
    streaming: bool


class UsageRecordRequest(Contract):
    request_id: Identifier
    provider_usage: dict[str, object] | None = None
    status: Literal["actual", "usage_unknown"]
