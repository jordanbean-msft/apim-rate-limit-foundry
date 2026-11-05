from typing import Any

from apim_rate_limit_foundry.models import ApiProtocol, Usage
from apim_rate_limit_foundry.normalization.common import counter, details, known_fields
from apim_rate_limit_foundry.normalization.incomplete import IncompleteUsageError


def normalize_openai(data: dict[str, Any], protocol: ApiProtocol) -> Usage:
    chat = protocol == "openai-chat"
    input_name, output_name = (
        ("prompt_tokens", "completion_tokens") if chat else ("input_tokens", "output_tokens")
    )
    input_details = "prompt_tokens_details" if chat else "input_tokens_details"
    output_details = "completion_tokens_details" if chat else "output_tokens_details"
    known_fields(data, {input_name, output_name, "total_tokens", input_details, output_details})
    inputs, outputs = counter(data, input_name), counter(data, output_name)
    if "total_tokens" in data and counter(data, "total_tokens") != inputs + outputs:
        raise ValueError("Provider total_tokens does not match input plus output")
    normalized = {"input_tokens": inputs, "output_tokens": outputs}
    input_info = details(data, input_details)
    if input_info is not None:
        known_fields(input_info, {"cached_tokens", "audio_tokens"} if chat else {"cached_tokens"})
        if "audio_tokens" in input_info and counter(input_info, "audio_tokens"):
            raise IncompleteUsageError("Audio usage has no supported text price")
        if "cached_tokens" in input_info:
            normalized["cached_input_tokens"] = counter(input_info, "cached_tokens")
    output_info = details(data, output_details)
    if output_info is not None:
        known_fields(
            output_info,
            {
                "reasoning_tokens",
                "audio_tokens",
                "accepted_prediction_tokens",
                "rejected_prediction_tokens",
            }
            if chat
            else {"reasoning_tokens"},
        )
        for name in output_info:
            amount = counter(output_info, name)
            if amount > outputs:
                raise ValueError("Provider output detail exceeds total output")
            if name == "audio_tokens" and amount:
                raise IncompleteUsageError("Audio usage has no supported text price")
    return Usage(**normalized)
