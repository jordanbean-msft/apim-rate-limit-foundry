from pydantic import Field

from apim_rate_limit_foundry.models.usage_summary import UsageSummary


class CallerUsage(UsageSummary):
    caller_ref: str
    display_label: str | None = None
    streaming: bool
    denied_policy_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Unique denied requests per binding policy, excluding merely matched rules.",
    )
    actual_cost_micro_usd: int = Field(
        default=0,
        description="Effective charges with trusted actual usage and known cache counters.",
    )
    conservative_cost_micro_usd: int = Field(
        default=0,
        description="Effective charges with unresolved or estimated usage; included in total cost.",
    )
