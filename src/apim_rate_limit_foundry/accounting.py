"""Validate supported provider text usage and price it in integer micro-USD.

These pure helpers neither read live prices nor mutate spend. Callers must supply
the price snapshot captured at admission, rather than a subsequently edited card.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any

from apim_rate_limit_foundry.models.price import Price


def digest(*values: str) -> str:
    """Hash an ordered, unambiguous JSON tuple for stable storage and counter IDs."""
    payload = json.dumps(values, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def utc_month(now: datetime | None = None) -> tuple[str, datetime]:
    """Return the UTC ``YYYY-MM`` accounting bucket and next month's UTC boundary."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        reset = start.replace(year=start.year + 1, month=1)
    else:
        reset = start.replace(month=start.month + 1)
    return start.strftime("%Y-%m"), reset


def normalize_openai_usage(provider_usage: dict[str, Any], protocol: str) -> dict[str, int]:
    """Normalize Chat/Responses text usage into input, cached-input and output counts.

    Cached input is a subset of input, not an additional token category. Reject
    unknown fields, inconsistent totals, unsupported priced modalities and invalid
    counters with ``ValueError`` so callers can explicitly record unknown usage
    instead of inventing a charge. Output details are subsets, not extra charges.
    """
    if protocol == "openai-chat":
        input_name, output_name, details_name = (
            "prompt_tokens",
            "completion_tokens",
            "prompt_tokens_details",
        )
        output_details_name = "completion_tokens_details"
    elif protocol == "openai-responses":
        input_name, output_name, details_name = (
            "input_tokens",
            "output_tokens",
            "input_tokens_details",
        )
        output_details_name = "output_tokens_details"
    else:
        raise ValueError("Unsupported OpenAI protocol")
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
    details_value = provider_usage.get(details_name)
    details = {} if details_value is None else details_value
    if not isinstance(details, dict):
        raise ValueError("Provider input token details must be an object")
    if set(details) - {"cached_tokens", "cache_write_tokens", "audio_tokens", "text_tokens"}:
        raise ValueError("Provider input details contain unsupported token categories")
    if "cache_write_tokens" in details and _counter(details, "cache_write_tokens"):
        raise ValueError("Cache-write usage has no supported text price")
    if "audio_tokens" in details and _counter(details, "audio_tokens"):
        raise ValueError("Audio usage has no supported text price")
    cached = _counter(details, "cached_tokens") if "cached_tokens" in details else 0
    if cached > input_tokens or (
        "text_tokens" in details and _counter(details, "text_tokens") > input_tokens
    ):
        raise ValueError("Cached input tokens cannot exceed total input tokens")
    output_details_value = provider_usage.get(output_details_name)
    output_details = {} if output_details_value is None else output_details_value
    if not isinstance(output_details, dict):
        raise ValueError("Provider output token details must be an object")
    if set(output_details) - {
        "reasoning_tokens",
        "audio_tokens",
        "text_tokens",
        "accepted_prediction_tokens",
        "rejected_prediction_tokens",
    }:
        raise ValueError("Provider output details contain unsupported token categories")
    if output_details.get("audio_tokens") is not None and _counter(output_details, "audio_tokens"):
        raise ValueError("Audio usage has no supported text price")
    for field in (
        "reasoning_tokens",
        "text_tokens",
        "accepted_prediction_tokens",
        "rejected_prediction_tokens",
    ):
        if field in output_details and _counter(output_details, field) > output_tokens:
            raise ValueError("Provider output detail exceeds total output")
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
    }


def _counter(data: dict[str, Any], field: str) -> int:
    """Require a bounded non-negative integer, excluding Python's boolean subtype."""
    value = data.get(field)
    if type(value) is not int or value < 0 or value > 9_000_000_000_000:
        raise ValueError(f"{field} is outside the supported non-negative integer range")
    return value


def cost_micro_usd(price: Price, usage: dict[str, int]) -> int:
    """Price normalized usage, rounding the combined request charge upward once.

    USD per million tokens multiplied by token counts is already micro-USD; no
    floating-point conversion or extra million-factor division is needed. Cached
    tokens replace ordinary input tokens. Reject overlarge charges or cached
    counts exceeding input; other counter validation belongs to normalization.
    """
    inputs = usage["input_tokens"]
    cached = usage["cached_input_tokens"]
    outputs = usage["output_tokens"]
    if cached > inputs:
        raise ValueError("Cached input tokens cannot exceed total input tokens")
    amount = (
        Decimal(inputs - cached) * price.input_per_million
        + Decimal(cached) * price.cached_input_per_million
        + Decimal(outputs) * price.output_per_million
    )
    result = int(amount.to_integral_value(rounding=ROUND_CEILING))
    if result > 9_000_000_000_000:
        raise ValueError("Cost exceeds supported integer range")
    return result
