from typing import Any

from apim_rate_limit_foundry.models import Usage
from apim_rate_limit_foundry.normalization.common import counter, details, known_fields
from apim_rate_limit_foundry.normalization.incomplete import IncompleteUsageError


def normalize_anthropic(data: dict[str, Any]) -> Usage:
    known_fields(
        data,
        {
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_creation",
            "server_tool_use",
            "service_tier",
            "inference_geo",
        },
    )
    uncached, outputs = counter(data, "input_tokens"), counter(data, "output_tokens")
    reads, writes = (
        counter(data, "cache_read_input_tokens"),
        counter(data, "cache_creation_input_tokens"),
    )
    creation = details(data, "cache_creation")
    if writes and creation is None:
        raise IncompleteUsageError("Cache creation TTL breakdown is missing")
    write_5m = write_1h = 0
    if creation is not None:
        known_fields(creation, {"ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"})
        if writes:
            write_5m = counter(creation, "ephemeral_5m_input_tokens")
            write_1h = counter(creation, "ephemeral_1h_input_tokens")
        else:
            write_5m = (
                counter(creation, "ephemeral_5m_input_tokens")
                if "ephemeral_5m_input_tokens" in creation
                else 0
            )
            write_1h = (
                counter(creation, "ephemeral_1h_input_tokens")
                if "ephemeral_1h_input_tokens" in creation
                else 0
            )
    if write_5m + write_1h != writes:
        raise ValueError("Cache creation TTL counters do not match aggregate writes")
    tools = details(data, "server_tool_use")
    if tools is not None:
        known_fields(tools, {"web_search_requests", "web_fetch_requests"})
        if any(counter(tools, name) for name in tools):
            raise IncompleteUsageError("Separately billed server tools are unsupported")
    if data.get("service_tier", "standard") != "standard":
        raise IncompleteUsageError("Unsupported provider billing tier")
    if data.get("inference_geo", "not_available") not in ("not_available", "global"):
        raise IncompleteUsageError("Geographic inference pricing is not configured")
    return Usage(
        input_tokens=uncached + reads + writes,
        output_tokens=outputs,
        cached_input_tokens=reads,
        cache_write_input_tokens_5m=write_5m,
        cache_write_input_tokens_1h=write_1h,
    )
