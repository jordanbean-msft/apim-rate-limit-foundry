from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.models import Reserve, Settle, Usage


def _zero_write_fields(usage: Usage) -> set[str]:
    return {
        name
        for name in ("cache_write_input_tokens_5m", "cache_write_input_tokens_1h")
        if getattr(usage, name) == 0
    }


def reserve_fingerprint(request: Reserve) -> str:
    exclusions: dict = {"usage": _zero_write_fields(request.usage)}
    if request.api_protocol in (None, "openai-chat"):
        exclusions["api_protocol"] = True
    return digest(request.model_dump_json(exclude=exclusions))


def settlement_fingerprint(request: Settle, usage: Usage, cached_reported: bool) -> str:
    normalized = Settle(reservation_id=request.reservation_id, usage=usage, status=request.status)
    return digest(
        normalized.model_dump_json(
            exclude={
                "provider_usage": True,
                "usage": _zero_write_fields(usage),
            }
        ),
        str(cached_reported),
    )
