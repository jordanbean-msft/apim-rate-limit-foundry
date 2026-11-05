from apim_rate_limit_foundry.models import Reserve, Settle, Usage
from apim_rate_limit_foundry.normalization.anthropic import normalize_anthropic
from apim_rate_limit_foundry.normalization.openai import normalize_openai


def normalize_settlement_usage(request: Settle, original: Reserve) -> Usage:
    usage = request.usage
    if request.provider_usage is not None:
        if usage is not None or request.status != "actual":
            raise ValueError("Provider usage requires actual settlement without normalized usage")
        if original.effective_protocol is None:
            raise ValueError("Provider usage is only supported for Foundry requests")
        usage = (
            normalize_anthropic(request.provider_usage)
            if original.effective_protocol == "anthropic-messages"
            else normalize_openai(request.provider_usage, original.effective_protocol)
        )
    if usage is None:
        raise ValueError("Settlement usage is required")
    if request.status == "conservative":
        return usage
    required = {
        "foundry": {"input_tokens", "output_tokens"},
        "document-intelligence": {"pages"},
        "language": {"text_records"},
    }[original.service]
    if not required.issubset(usage.model_fields_set):
        raise ValueError("Actual usage is missing required service counters")
    writes = {"cache_write_input_tokens_5m", "cache_write_input_tokens_1h"}
    if original.effective_protocol == "anthropic-messages":
        if not (writes | {"cached_input_tokens"}).issubset(usage.model_fields_set):
            raise ValueError("Actual Anthropic usage requires explicit read/write cache counters")
    elif usage.cache_write_input_tokens_5m or usage.cache_write_input_tokens_1h:
        raise ValueError("Cache writes require an Anthropic reservation")
    for name in ("input_tokens", "output_tokens", "pages", "text_records", "requests"):
        if getattr(usage, name) > getattr(original.usage, name):
            raise ValueError("Actual usage exceeds admitted hard bound; retain reservation")
    return usage
