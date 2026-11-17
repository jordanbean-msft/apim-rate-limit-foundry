"""Shared JSON scalar constraints, including decimal-string-only monetary rates."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:@*-]+$")]
ApiProtocol = Literal["openai-chat", "openai-responses"]
# Registered model aliases, deployment names and price models share this bounded shape.
SAFE_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
SAFE_NAME_PATTERN = rf"^{SAFE_NAME}$"


def _decimal_string(value: object) -> object:
    """Reject numeric JSON prices before Decimal conversion can preserve float error."""
    if not isinstance(value, str | Decimal):
        raise ValueError("Prices must be decimal USD strings, never floats")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    Field(ge=0, le=1_000_000, allow_inf_nan=False),
]
