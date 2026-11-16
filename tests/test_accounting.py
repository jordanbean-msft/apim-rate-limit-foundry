from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apim_rate_limit_foundry.accounting import (
    cost_micro_usd,
    normalize_openai_usage,
    price_usage,
    utc_month,
)
from apim_rate_limit_foundry.models import Price
from apim_rate_limit_foundry.models.model_bounds import ModelBounds
from apim_rate_limit_foundry.models.usage_counts import UsageCounts

BOUNDS = ModelBounds(max_input_tokens=1000, max_output_tokens=500)


@pytest.fixture
def price() -> Price:
    return Price(
        id="price",
        model="model",
        version="v1",
        input_per_million="0.2",
        cached_input_per_million="0.05",
        output_per_million="0.8",
    )


def test_normalizes_chat_and_responses_usage_and_cached_input(price: Price) -> None:
    chat = normalize_openai_usage(
        {
            "prompt_tokens": 1_000_000,
            "completion_tokens": 100_000,
            "total_tokens": 1_100_000,
            "prompt_tokens_details": {"cached_tokens": 100_000},
            "latency_checkpoint": {"engine_ttft_ms": 10},
        },
        "openai-chat",
    )
    responses = normalize_openai_usage(
        {
            "input_tokens": 1_000_000,
            "output_tokens": 100_000,
            "input_tokens_details": {"cached_tokens": 100_000, "cache_write_tokens": 0},
        },
        "openai-responses",
    )

    assert (
        chat
        == responses
        == UsageCounts(input_tokens=1_000_000, cached_input_tokens=100_000, output_tokens=100_000)
    )
    assert cost_micro_usd(price, chat) == 265_000


def test_cache_write_tokens_use_their_own_rate_or_the_uncached_input_rate(price: Price) -> None:
    usage = normalize_openai_usage(
        {
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 200_000, "cache_write_tokens": 300_000},
        },
        "openai-responses",
    )

    assert usage.cache_write_tokens == 300_000
    assert usage.uncached_input_tokens == 500_000
    assert cost_micro_usd(price, usage) == 500_000 * 0.2 + 200_000 * 0.05 + 300_000 * 0.2
    priced = price.model_copy(update={"cache_write_per_million": Decimal("0.25")})
    assert cost_micro_usd(priced, usage) == 500_000 * 0.2 + 200_000 * 0.05 + 300_000 * 0.25


def test_null_audio_tokens_are_ignored_for_input_and_output_details() -> None:
    usage = normalize_openai_usage(
        {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 1, "audio_tokens": None},
            "completion_tokens_details": {"audio_tokens": None},
        },
        "openai-chat",
    )
    assert usage.cached_input_tokens == 1


def test_nonzero_audio_tokens_have_no_price() -> None:
    with pytest.raises(ValueError, match="Audio"):
        normalize_openai_usage(
            {
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "prompt_tokens_details": {"audio_tokens": 1},
            },
            "openai-chat",
        )


@pytest.mark.parametrize("cache_writes", [-1, True, 0.0, None])
def test_usage_rejects_invalid_cache_writes(cache_writes: object) -> None:
    with pytest.raises(ValueError):
        normalize_openai_usage(
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": cache_writes},
            },
            "openai-responses",
        )


def test_usage_rejects_bad_totals_and_cache_counts() -> None:
    with pytest.raises(ValueError, match="total_tokens"):
        normalize_openai_usage(
            {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 4}, "openai-chat"
        )
    with pytest.raises(ValueError, match="Cached"):
        normalize_openai_usage(
            {
                "input_tokens": 1,
                "output_tokens": 2,
                "input_tokens_details": {"cached_tokens": 2},
            },
            "openai-responses",
        )
    with pytest.raises(ValueError, match="Cached"):
        normalize_openai_usage(
            {
                "input_tokens": 3,
                "output_tokens": 2,
                "input_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 2},
            },
            "openai-responses",
        )


def test_actual_usage_above_pinned_bounds_is_priced_with_real_counts_and_flagged(
    price: Price,
) -> None:
    priced = price_usage(
        "actual",
        {"prompt_tokens": 2000, "completion_tokens": 600},
        "openai-chat",
        price,
        BOUNDS,
    )

    assert priced.status == "actual"
    assert priced.out_of_bounds is True
    assert priced.counts == UsageCounts(input_tokens=2000, output_tokens=600)
    assert priced.cost_basis == "provider_usage"
    assert priced.cost_micro_usd == cost_micro_usd(price, priced.counts)


def test_usage_within_bounds_is_not_flagged(price: Price) -> None:
    priced = price_usage(
        "actual", {"prompt_tokens": 1000, "completion_tokens": 500}, "openai-chat", price, BOUNDS
    )
    assert priced.out_of_bounds is False


@pytest.mark.parametrize(
    ("status", "provider_usage", "reason"),
    [
        ("usage_unknown", None, "reported_unknown"),
        ("actual", None, "provider_usage_missing"),
        ("actual", {"prompt_tokens": "many"}, "provider_usage_invalid"),
    ],
)
def test_unknown_usage_is_charged_the_pinned_upper_bound(
    price: Price, status: str, provider_usage: dict | None, reason: str
) -> None:
    priced = price_usage(status, provider_usage, "openai-chat", price, BOUNDS)  # type: ignore[arg-type]

    assert priced.status == "usage_unknown"
    assert priced.reason == reason
    assert priced.counts is None
    assert priced.cost_basis == "estimated_upper_bound"
    assert priced.cost_micro_usd == 1000 * 0.2 + 500 * 0.8


def test_month_uses_utc_calendar_and_rolls_over_december() -> None:
    month, reset = utc_month(datetime(2030, 12, 31, 23, 59, tzinfo=UTC))
    assert month == "2030-12"
    assert reset == datetime(2031, 1, 1, tzinfo=UTC)
