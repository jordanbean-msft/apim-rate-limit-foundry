"""Stable identifiers derived from budgets and tenant/user identity."""

import hashlib

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.models import Budget


def budget_counter_key(budget: Budget, month: str) -> str:
    """Identify spend by subject/model/month rather than editable budget record ID."""
    return digest(budget.tenant_id, budget.subject_type, budget.subject_id, month, budget.model)


def opaque(*parts: str) -> str:
    """Produce stable telemetry references without emitting raw tenant/user identifiers."""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
