"""Durable event envelope for request, usage and audit records."""

from datetime import UTC, datetime

from apim_rate_limit_foundry.stores.contracts import Record


def event(kind: str, record_id: str, tenant: str, principal: str, data: Record) -> Record:
    """Wrap a supplied payload with durable identity and a UTC creation timestamp."""
    return {
        "id": record_id,
        "kind": kind,
        "tenant_id": tenant,
        "principal_id": principal,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }
