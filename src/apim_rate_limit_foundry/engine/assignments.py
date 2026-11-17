"""Shared selection of enabled tenant assignments from configuration records."""

from apim_rate_limit_foundry.models import Assignment
from apim_rate_limit_foundry.stores.contracts import Record


def enabled_assignments(
    records: list[Record], tenant_id: str, principal_id: str | None = None
) -> list[Assignment]:
    """Return the tenant's enabled assignments, narrowed to one principal when given."""
    return [
        Assignment.model_validate(record)
        for record in records
        if record.get("tenant_id") == tenant_id
        and record.get("enabled") is True
        and (principal_id is None or record.get("principal_id") == principal_id)
    ]
