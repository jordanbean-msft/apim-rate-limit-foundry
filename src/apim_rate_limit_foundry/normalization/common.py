from typing import Any

from apim_rate_limit_foundry.normalization.incomplete import IncompleteUsageError


def counter(data: dict[str, Any], name: str) -> int:
    if name not in data:
        raise IncompleteUsageError(f"Missing provider usage counter: {name}")
    value = data[name]
    if type(value) is not int or not 0 <= value <= 9_000_000_000_000:
        raise ValueError(f"Invalid provider usage counter: {name}")
    return value


def known_fields(data: dict[str, Any], allowed: set[str]) -> None:
    if set(data) - allowed:
        raise IncompleteUsageError("Unsupported provider usage dimensions")


def details(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Invalid provider usage details: {name}")
    return value
