import pytest

from apim_rate_limit_foundry.accounting import cost_micro_usd, normalize_openai_usage
from apim_rate_limit_foundry.models import Price
from apim_rate_limit_foundry.models.usage_counts import UsageCounts

BASE = {"prompt_tokens": 100, "completion_tokens": 50}


@pytest.mark.parametrize(
    ("usage", "protocol", "message"),
    [
        (BASE, "anthropic", "Unsupported OpenAI protocol"),
        ({**BASE, "surprise_tokens": 1}, "openai-chat", "unsupported token categories"),
        (
            {**BASE, "prompt_tokens_details": {"text_tokens": 101}},
            "openai-chat",
            "input detail exceeds total input",
        ),
        (
            {**BASE, "completion_tokens_details": {"reasoning_tokens": 51}},
            "openai-chat",
            "output detail exceeds total output",
        ),
        ({**BASE, "prompt_tokens_details": "cached"}, "openai-chat", "must be an object"),
        (
            {**BASE, "prompt_tokens_details": {"video_tokens": 1}},
            "openai-chat",
            "input details contain unsupported",
        ),
        (
            {**BASE, "completion_tokens_details": {"video_tokens": 1}},
            "openai-chat",
            "output details contain unsupported",
        ),
    ],
)
def test_unsupported_or_inconsistent_provider_usage_is_rejected(
    usage: dict, protocol: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_openai_usage(usage, protocol)


def test_null_detail_objects_are_treated_as_absent() -> None:
    counts = normalize_openai_usage({**BASE, "prompt_tokens_details": None}, "openai-chat")

    assert (counts.input_tokens, counts.cached_input_tokens) == (100, 0)


def test_costs_beyond_the_supported_integer_range_are_rejected() -> None:
    price = Price(
        id="price",
        model="model",
        version="v1",
        input_per_million="1000000",
        cached_input_per_million="0",
        output_per_million="0",
    )

    with pytest.raises(ValueError, match="integer range"):
        cost_micro_usd(price, UsageCounts(input_tokens=9_000_000_000_000, output_tokens=0))
