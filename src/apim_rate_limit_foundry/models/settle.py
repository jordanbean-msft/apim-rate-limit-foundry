import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier
from apim_rate_limit_foundry.models.usage import Usage


class Settle(Contract):
    """Exactly one usage source; raw metadata is parsed using the saved reservation protocol."""

    reservation_id: Identifier
    usage: Usage | None = None
    status: Literal["actual", "conservative"]
    provider_usage: dict[str, Any] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def exactly_one_usage_source(self) -> "Settle":
        if (self.usage is None) == (self.provider_usage is None):
            raise ValueError("Supply exactly one of usage or provider_usage")
        if self.provider_usage is not None and self.status != "actual":
            raise ValueError("Provider usage is only accepted for actual settlement")
        return self

    @field_validator("provider_usage")
    @classmethod
    def bounded_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        pending: list[tuple[Any, int]] = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 3:
                raise ValueError("Provider usage metadata is too deeply nested")
            if isinstance(item, dict):
                if any(not isinstance(key, str) or len(key) > 80 for key in item):
                    raise ValueError("Invalid provider usage metadata key")
                pending.extend((child, depth + 1) for child in item.values())
            elif type(item) is int:
                if not 0 <= item <= 9_000_000_000_000:
                    raise ValueError("Provider counters exceed the supported integer range")
            elif item is not None and (not isinstance(item, str) or len(item) > 128):
                raise ValueError("Provider counters must be nonnegative integers, never bool/float")
        if len(json.dumps(value).encode()) > 8192:
            raise ValueError("Provider usage metadata exceeds 8192 bytes")
        return value
