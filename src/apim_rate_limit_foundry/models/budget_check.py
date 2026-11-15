"""Gateway JSON inputs; decision and finalized-event dictionaries are returned by the engine."""

from typing import Literal

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class BudgetCheck(Contract):
    """Admission input binding an APIM request ID to identity and model context.

    APIM supplies the subscription/identity fields after validating the caller.
    The model is a configured alias, not a provider URL. Saved context is reused
    for pricing, hierarchy attribution and idempotent usage finalization.
    """

    request_id: Identifier
    tenant_id: Identifier
    principal_id: Identifier
    subscription_id: Identifier
    model: Identifier
    api_protocol: Literal["openai-chat", "openai-responses"]
    streaming: bool


class UsageRecordRequest(Contract):
    """Finalize an admitted request using original provider counters or unknown status.

    Actual usage requires a protocol-specific provider_usage object for validation;
    usage_unknown must not contain fabricated counters. The response is an event
    plus a replay flag; acceptance promises Redis state, not durable persistence.
    """

    request_id: Identifier
    provider_usage: dict[str, object] | None = None
    status: Literal["actual", "usage_unknown"]
