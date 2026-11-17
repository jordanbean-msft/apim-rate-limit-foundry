"""The ``budget_status`` event, emitted from both live reads and accepted usage."""

from apim_rate_limit_foundry.engine.keys import opaque
from apim_rate_limit_foundry.engine.spend import remaining_micro_usd
from apim_rate_limit_foundry.telemetry import emit


def emit_budget_status(
    *,
    tenant_id: str,
    month: str,
    budget_id: str,
    subject_type: str,
    subject_id: str,
    model: str,
    limit_micro_usd: int,
    spent_micro_usd: int,
    team_id: str | None,
    department_id: str | None,
) -> None:
    """Emit one cap's balance, replacing a user subject with an opaque reference."""
    user_ref = opaque(tenant_id, subject_id) if subject_type == "user" else None
    emit(
        "budget_status",
        month=month,
        budget_id=budget_id,
        subject_type=subject_type,
        subject_id=user_ref or subject_id,
        model=model,
        limit_micro_usd=limit_micro_usd,
        spent_micro_usd=spent_micro_usd,
        remaining_micro_usd=remaining_micro_usd(limit_micro_usd, spent_micro_usd),
        user_ref=user_ref,
        team_id=team_id,
        department_id=department_id,
    )
