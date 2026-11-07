"""Stable pseudonymous correlation keys, not authentication or anonymization."""

import hashlib


def caller_ref(tenant_id: str, subscription_id: str) -> str:
    """Hash UTF-8 tenant + LF + subscription ID (case preserved), with no prefix.

    Identifiers cannot contain LF; reject it here too so the separator is unambiguous.
    The hash is full lowercase SHA-256 hex, with no trailing newline in the input.
    """
    if "\n" in tenant_id or "\n" in subscription_id:
        raise ValueError("Caller identifiers must not contain newline")
    identity = tenant_id + "\n" + subscription_id
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
