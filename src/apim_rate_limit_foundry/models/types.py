from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:@*-]+$")]
ApiProtocol = Literal["openai-chat", "openai-responses"]


def _decimal_string(value: object) -> object:
    if not isinstance(value, str | Decimal):
        raise ValueError("Prices must be decimal USD strings, never floats")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    Field(ge=0, le=1_000_000, allow_inf_nan=False),
]
