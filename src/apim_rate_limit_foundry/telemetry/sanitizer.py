"""Second privacy boundary: copy only bounded, allowlisted values into telemetry.

Callers minimize what they emit; this module guarantees that unknown fields,
invalid identifiers, nonfinite numbers and oversized values never leave the
process. It is not a general-purpose serializer for request or provider objects.
"""

import math
import re
from collections.abc import Mapping
from typing import Any

from apim_rate_limit_foundry.telemetry.allowlist import (
    EVENTS,
    FALLBACK_EVENT,
    FIELDS,
    LIST_FIELDS,
    TEXT_FIELDS,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_SUBSCRIPTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}\Z")
_MAX_TEXT_LENGTH = 160
_MAX_LIST_ITEMS = 128
_UNSAFE_TEXT = ("\r", "\n", "?", "#")
_DROP = object()


def safe_event(value: object) -> str:
    """Collapse unknown log messages to a fixed event name, never raw free text."""
    return value if isinstance(value, str) and value in EVENTS else FALLBACK_EVENT


def safe_id(value: str | None) -> str | None:
    """Accept only bounded correlation/attribute identifiers safe for export."""
    return value if value and _SAFE_ID.fullmatch(value) else None


def _safe_text(value: str) -> bool:
    return len(value) <= _MAX_TEXT_LENGTH and not any(c in value for c in _UNSAFE_TEXT)


def _safe_value(key: str, value: Any) -> Any:
    """Return the exportable form of one value, or ``_DROP`` when it is unsafe."""
    if key in ("model", "budget_model") and value == "*":
        return value
    if key == "subscription_id":
        return value if isinstance(value, str) and _SAFE_SUBSCRIPTION_ID.fullmatch(value) else _DROP
    if key == "streaming":
        return value if isinstance(value, bool) else _DROP
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        accepted = _safe_text(value) if key in TEXT_FIELDS else safe_id(value)
        return value if accepted else _DROP
    if key in LIST_FIELDS and isinstance(value, list):
        return [item for item in value[:_MAX_LIST_ITEMS] if isinstance(item, str) and safe_id(item)]
    return _DROP


def safe_attributes(values: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only allowlisted, bounded scalar/list attributes into logs and spans."""
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in FIELDS and value is not None:
            safe = _safe_value(key, value)
            if safe is not _DROP:
                result[key] = safe
    return result
