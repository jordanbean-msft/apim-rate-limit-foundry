"""Validate supported provider text usage and price it in integer micro-USD.

These pure helpers neither read live prices nor mutate spend. Callers must supply
the price snapshot captured at admission, rather than a subsequently edited card.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal

from apim_rate_limit_foundry.models.model_bounds import ModelBounds
from apim_rate_limit_foundry.models.price import Price
from apim_rate_limit_foundry.models.priced_usage import PricedUsage, UsageReason
from apim_rate_limit_foundry.models.usage_counts import UsageCounts

MAX_COUNTER = 9_000_000_000_000
INPUT_DETAIL_FIELDS = {"cached_tokens", "cache_write_tokens", "audio_tokens", "text_tokens"}
OUTPUT_DETAIL_FIELDS = {
    "reasoning_tokens",
    "audio_tokens",
    "text_tokens",
    "accepted_prediction_tokens",
    "rejected_prediction_tokens",
}
PROTOCOL_FIELDS = {
    "openai-chat": (
        "prompt_tokens",
        "completion_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    ),
    "openai-responses": (
        "input_tokens",
        "output_tokens",
        "input_tokens_details",
        "output_tokens_details",
    ),
}


def digest(*values: str) -> str:
    """Hash an ordered, unambiguous JSON tuple for stable storage and counter IDs."""
    payload = json.dumps(values, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def usage_partition(tenant_id: str, month: str) -> str:
    """Name the durable history partition holding one tenant's usage for one UTC month."""
    return f"usage:{tenant_id}:{month}"


def utc_month(now: datetime | None = None) -> tuple[str, datetime]:
    """Return the UTC ``YYYY-MM`` accounting bucket and next month's UTC boundary."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        reset = start.replace(year=start.year + 1, month=1)
    else:
        reset = start.replace(month=start.month + 1)
    return start.strftime("%Y-%m"), reset


def normalize_openai_usage(provider_usage: dict[str, Any], protocol: str) -> UsageCounts:
    """Normalize Chat/Responses text usage into input, cached, cache-write and output counts.

    Cached and cache-write input are subsets of input, not additional token
    categories. Reject unknown fields, inconsistent totals, unsupported priced
    modalities and invalid counters with ``ValueError`` so callers can explicitly
    record unknown usage instead of inventing a charge. Output details are subsets,
    not extra charges.
    """
    fields = PROTOCOL_FIELDS.get(protocol)
    if fields is None:
        raise ValueError("Unsupported OpenAI protocol")
    input_name, output_name, details_name, output_details_name = fields
    if set(provider_usage) - {
        input_name,
        output_name,
        "total_tokens",
        details_name,
        output_details_name,
        "latency_checkpoint",
    }:
        raise ValueError("Provider usage contains unsupported token categories")
    input_tokens = _counter(provider_usage, input_name)
    output_tokens = _counter(provider_usage, output_name)
    if "total_tokens" in provider_usage:
        total = _counter(provider_usage, "total_tokens")
        if total != input_tokens + output_tokens:
            raise ValueError("Provider total_tokens does not match input plus output")
    details = _details(provider_usage, details_name, INPUT_DETAIL_FIELDS, "input")
    _reject_audio(details)
    if "text_tokens" in details and _counter(details, "text_tokens") > input_tokens:
        raise ValueError("Provider input detail exceeds total input")
    output_details = _details(provider_usage, output_details_name, OUTPUT_DETAIL_FIELDS, "output")
    _reject_audio(output_details)
    for field in OUTPUT_DETAIL_FIELDS - {"audio_tokens"}:
        if field in output_details and _counter(output_details, field) > output_tokens:
            raise ValueError("Provider output detail exceeds total output")
    return UsageCounts(
        input_tokens=input_tokens,
        cached_input_tokens=_counter(details, "cached_tokens") if "cached_tokens" in details else 0,
        cache_write_tokens=(
            _counter(details, "cache_write_tokens") if "cache_write_tokens" in details else 0
        ),
        output_tokens=output_tokens,
    )


def _details(
    provider_usage: dict[str, Any], name: str, allowed: set[str], direction: str
) -> dict[str, Any]:
    """Return an optional token-detail object after rejecting unsupported categories."""
    value = provider_usage.get(name)
    details = {} if value is None else value
    if not isinstance(details, dict):
        raise ValueError(f"Provider {direction} token details must be an object")
    if set(details) - allowed:
        raise ValueError(f"Provider {direction} details contain unsupported token categories")
    return details


def _reject_audio(details: dict[str, Any]) -> None:
    """Reject nonzero audio usage; an explicit null counts as absent."""
    if details.get("audio_tokens") is not None and _counter(details, "audio_tokens"):
        raise ValueError("Audio usage has no supported text price")


def _counter(data: dict[str, Any], field: str) -> int:
    """Require a bounded non-negative integer, excluding Python's boolean subtype."""
    value = data.get(field)
    if type(value) is not int or value < 0 or value > MAX_COUNTER:
        raise ValueError(f"{field} is outside the supported non-negative integer range")
    return value


def cost_micro_usd(price: Price, usage: UsageCounts) -> int:
    """Price normalized usage, rounding the combined request charge upward once.

    USD per million tokens multiplied by token counts is already micro-USD; no
    floating-point conversion or extra million-factor division is needed. Cached
    tokens and cache-write tokens replace ordinary input tokens; cache-write tokens
    use the input rate unless the price card supplies a cache-write rate. Reject
    overlarge charges.
    """
    cache_write_rate = (
        price.input_per_million
        if price.cache_write_per_million is None
        else price.cache_write_per_million
    )
    amount = (
        Decimal(usage.uncached_input_tokens) * price.input_per_million
        + Decimal(usage.cached_input_tokens) * price.cached_input_per_million
        + Decimal(usage.cache_write_tokens) * cache_write_rate
        + Decimal(usage.output_tokens) * price.output_per_million
    )
    result = int(amount.to_integral_value(rounding=ROUND_CEILING))
    if result > MAX_COUNTER:
        raise ValueError("Cost exceeds supported integer range")
    return result


def estimate_upper_bound_cost(price: Price, bounds: ModelBounds) -> int:
    """Charge the pinned maximum input (uncached) and maximum output for unknown usage."""
    ceiling = UsageCounts(
        input_tokens=bounds.max_input_tokens, output_tokens=bounds.max_output_tokens
    )
    return cost_micro_usd(price, ceiling)


def price_usage(
    status: Literal["actual", "usage_unknown"],
    provider_usage: dict[str, Any] | None,
    protocol: str,
    price: Price,
    bounds: ModelBounds,
) -> PricedUsage:
    """Price valid provider usage; otherwise charge the pinned upper bound.

    Counts above the pinned bounds are priced as reported and flagged. Unknown,
    missing or invalid usage never becomes a zero-cost request: it carries no
    token counts and the ``estimated_upper_bound`` basis.
    """
    reason: UsageReason
    if status == "actual" and provider_usage is not None:
        try:
            counts = normalize_openai_usage(provider_usage, protocol)
            cost = cost_micro_usd(price, counts)
        except ValueError:
            reason = "provider_usage_invalid"
        else:
            return PricedUsage(
                status="actual",
                reason="provider_usage",
                counts=counts,
                cost_micro_usd=cost,
                cost_basis="provider_usage",
                out_of_bounds=(
                    counts.input_tokens > bounds.max_input_tokens
                    or counts.output_tokens > bounds.max_output_tokens
                ),
            )
    else:
        reason = "provider_usage_missing" if status == "actual" else "reported_unknown"
    return PricedUsage(
        status="usage_unknown",
        reason=reason,
        counts=None,
        cost_micro_usd=estimate_upper_bound_cost(price, bounds),
        cost_basis="estimated_upper_bound",
    )
