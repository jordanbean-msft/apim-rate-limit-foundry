import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import ApiProtocol, Assignment, Policy, Price, Reserve, Usage


def digest(*values: str) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def window(period: str, now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(UTC)
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        start = now.replace(second=0, microsecond=0)
        if period in ("hour", "day"):
            start = start.replace(minute=0)
        if period == "day":
            start = start.replace(hour=0)
        end = (
            start
            + {
                "minute": timedelta(minutes=1),
                "hour": timedelta(hours=1),
                "day": timedelta(days=1),
            }[period]
        )
    return start, end


def cost(
    price: Price,
    usage: Usage,
    conservative: bool,
    api_protocol: ApiProtocol | None = None,
) -> int:
    cached = 0 if conservative else usage.cached_input_tokens
    write_5m = 0 if conservative else usage.cache_write_input_tokens_5m
    write_1h = 0 if conservative else usage.cache_write_input_tokens_1h
    input_rate = price.input_per_million
    if conservative and usage.input_tokens:
        input_rates = [input_rate, price.cached_input_per_million]
        if api_protocol == "anthropic-messages":
            input_rates.extend([price.cache_write_5m_per_million, price.cache_write_1h_per_million])
        if any(rate is None for rate in input_rates):
            raise ValueError("Unknown input, cached-input, or cache-write unit price")
        input_rate = max(rate for rate in input_rates if rate is not None)
    amounts = [
        (usage.input_tokens - cached - write_5m - write_1h, input_rate, 1),
        (cached, price.cached_input_per_million, 1),
        (write_5m, price.cache_write_5m_per_million, 1),
        (write_1h, price.cache_write_1h_per_million, 1),
        (usage.output_tokens, price.output_per_million, 1),
        (usage.pages, price.per_page, 1_000_000),
        (usage.text_records, price.per_text_record, 1_000_000),
        (usage.requests, price.per_request, 1_000_000),
    ]
    total = Decimal(0)
    for units, rate, scale in amounts:
        if units and rate is None:
            raise ValueError("Unknown unit price")
        total += units * (rate or Decimal(0)) * scale
    result = int(total.to_integral_value(rounding=ROUND_CEILING))
    if result > 9_000_000_000_000:
        raise ValueError("Cost exceeds supported integer range")
    return result


def validate_estimate(request: Reserve, settings: Settings) -> None:
    usage = request.usage
    if (
        usage.requests != 1
        or usage.cached_input_tokens
        or usage.cache_write_input_tokens_5m
        or usage.cache_write_input_tokens_1h
    ):
        raise ValueError("Reserve one request without predicted cached hits")
    if (
        usage.input_tokens > settings.max_input_tokens
        or usage.output_tokens > settings.max_output_tokens
    ):
        raise ValueError("Token bound exceeded")
    if usage.pages > settings.max_pages or usage.text_records > settings.max_text_records:
        raise ValueError("Service unit bound exceeded")
    if request.service == "foundry":
        if not usage.input_tokens or not usage.output_tokens or usage.pages or usage.text_records:
            raise ValueError("Foundry requires bounded input and maximum output tokens")
    elif request.service == "document-intelligence":
        if not request.document_bound_verified or not usage.pages:
            raise ValueError("Document admission requires a gateway-verified hard page bound")
        if usage.input_tokens or usage.output_tokens or usage.text_records:
            raise ValueError("Invalid document units")
    elif not usage.text_records or usage.input_tokens or usage.output_tokens or usage.pages:
        raise ValueError("Language requires bounded text records")


def matching(
    request: Reserve, policies: list[Policy], assignments: list[Assignment]
) -> list[Policy]:
    assigned = {
        policy_id
        for assignment in assignments
        if assignment.tenant_id == request.tenant_id
        and assignment.subscription_id == request.subscription_id
        for policy_id in assignment.policy_ids
    }
    bound = {policy_id for assignment in assignments for policy_id in assignment.policy_ids}
    return sorted(
        [
            p
            for p in policies
            if p.enabled
            and p.service == request.service
            and p.model in ("*", request.model)
            and p.tenant_id in ("*", request.tenant_id)
            and p.subscription_id in ("*", request.subscription_id)
            and (p.id not in bound or p.id in assigned)
        ],
        key=lambda p: (-p.priority, p.id),
    )


def debits(
    request: Reserve, policies: list[Policy], price: Price, now: datetime
) -> list[dict[str, Any]]:
    result = []
    for policy in policies:
        start, end = window(policy.period, now)
        usage = request.usage
        amount = {
            "cost": cost(price, usage, True, request.effective_protocol),
            "tokens": usage.input_tokens + usage.output_tokens,
            "requests": usage.requests,
            "pages": usage.pages,
            "text_records": usage.text_records,
        }[policy.metric]
        result.append(
            {
                "key": digest(
                    policy.id,
                    policy.metric,
                    policy.period,
                    "application-v1",
                    request.tenant_id,
                    request.subscription_id,
                    start.isoformat(),
                ),
                "policy_id": policy.id,
                "metric": policy.metric,
                "amount": amount,
                "limit": policy.limit,
                "reset_at": end.isoformat(),
            }
        )
    return result


def actual_debits(
    original: list[dict[str, Any]],
    price: Price,
    usage: Usage,
    conservative_input: bool = False,
    api_protocol: ApiProtocol | None = None,
) -> list[dict[str, Any]]:
    amounts = {
        "cost": cost(price, usage, conservative_input, api_protocol),
        "tokens": usage.input_tokens + usage.output_tokens,
        "requests": usage.requests,
        "pages": usage.pages,
        "text_records": usage.text_records,
    }
    return [{**d, "amount": amounts[d["metric"]]} for d in original]
