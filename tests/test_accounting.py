from datetime import UTC, datetime

import pytest

from apim_rate_limit_foundry.accounting import cost_micro_usd, normalize_openai_usage, utc_month
from apim_rate_limit_foundry.models import Price


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
        == {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 100_000,
        }
    )
    assert cost_micro_usd(price, chat) == 265_000


@pytest.mark.parametrize("cache_writes", [1, -1, True, 0.0, None])
def test_usage_rejects_unpriced_or_invalid_cache_writes(cache_writes: object) -> None:
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


def test_month_uses_utc_calendar_and_rolls_over_december() -> None:
    month, reset = utc_month(datetime(2030, 12, 31, 23, 59, tzinfo=UTC))
    assert month == "2030-12"
    assert reset == datetime(2031, 1, 1, tzinfo=UTC)
