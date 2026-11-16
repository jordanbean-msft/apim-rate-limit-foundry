from unittest.mock import patch

import pytest

from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Assignment, Budget, Organization
from apim_rate_limit_foundry.stores.contracts import Conflict, Record

TENANT = "tenant-1"


def organization(
    org_id: str, kind: str = "team", tenant: str = TENANT, department: str | None = "department-1"
) -> Record:
    return Organization(
        id=org_id,
        tenant_id=tenant,
        kind=kind,
        name=org_id,
        department_id=department if kind == "team" else None,
        business_unit="BU-ENG",
        cost_center="CC-100",
    ).model_dump(mode="json")


def assignment(principal: str = "user-2", team: str = "team-1", **changes: object) -> Record:
    return Assignment(
        id=f"assignment-{principal}",
        tenant_id=TENANT,
        principal_id=principal,
        team_id=team,
        department_id="department-1",
        **changes,
    ).model_dump(mode="json")


def budget(subject_type: str, subject_id: str, tenant: str = TENANT) -> Record:
    return Budget(
        id=f"budget-{subject_id}",
        tenant_id=tenant,
        name=subject_id,
        subject_type=subject_type,
        subject_id=subject_id,
        limit_micro_usd=500,
    ).model_dump(mode="json")


async def save(engine: Engine, collection: str, record: Record, tenant: str = TENANT) -> Record:
    return await engine.save_configuration(collection, record["id"], record, tenant, "admin")


async def test_save_rejects_unsupported_collections_bad_bodies_and_mismatched_ids(
    engine: Engine,
) -> None:
    valid = organization("team-9")

    with pytest.raises(ValueError, match="Unsupported"):
        await engine.save_configuration("audit", "x", valid, TENANT, "admin")
    with pytest.raises(ValueError, match="Invalid configuration record"):
        await engine.save_configuration("organizations", "team-9", {"id": "team-9"}, TENANT, "a")
    with pytest.raises(ValueError, match="Path ID"):
        await engine.save_configuration("organizations", "other", valid, TENANT, "admin")
    with pytest.raises(ValueError, match="tenant must match"):
        await save(engine, "organizations", organization("team-9", tenant="tenant-2"))
    assert await engine.repository.get("organizations", "team-9") is None


async def test_save_refuses_to_replace_another_tenants_record(engine: Engine) -> None:
    foreign = organization("shared", "department", tenant="tenant-2")
    await engine.repository.create("organizations", "shared", foreign)

    with pytest.raises(Conflict, match="another tenant"):
        await save(engine, "organizations", organization("shared", "department"))


async def test_save_writes_an_audited_record_and_invalidates_the_cache(engine: Engine) -> None:
    await engine.counters.cache_configuration({"organizations": []})

    saved = await save(engine, "organizations", organization("team-2"))

    assert saved["id"] == "team-2"
    assert await engine.counters.configuration() is None
    assert await engine.repository.get("organizations", "team-2") == saved


async def test_delete_ignores_missing_records_and_unknown_collections(engine: Engine) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        await engine.delete_configuration("audit", "x", TENANT, "admin")

    await engine.delete_configuration("budgets", "never-existed", TENANT, "admin")

    assert await engine.repository.get("budgets", "never-existed") is None


async def test_delete_rejects_other_tenants_records(engine: Engine) -> None:
    await engine.repository.create(
        "organizations", "foreign", organization("foreign", "department", tenant="tenant-2")
    )

    with pytest.raises(ValueError, match="tenant must match"):
        await engine.delete_configuration("organizations", "foreign", TENANT, "admin")


async def test_organization_units_in_use_cannot_be_deleted(engine: Engine) -> None:
    with pytest.raises(ValueError, match="child teams"):
        await engine.delete_configuration("organizations", "department-1", TENANT, "admin")
    with pytest.raises(ValueError, match="active assignments"):
        await engine.delete_configuration("organizations", "team-1", TENANT, "admin")

    await save(engine, "organizations", organization("team-empty"))
    await engine.delete_configuration("organizations", "team-empty", TENANT, "admin")

    assert "team-empty" not in {row["id"] for row in await engine.configuration("organizations")}


async def test_assignments_require_one_active_user_and_an_enabled_parent_chain(
    engine: Engine,
) -> None:
    await save(engine, "assignments", assignment("user-2"))

    with pytest.raises(ValueError, match="already exists"):
        await save(engine, "assignments", {**assignment("user-1"), "id": "duplicate-user-1"})
    with pytest.raises(ValueError, match="enabled team"):
        await save(engine, "assignments", assignment("user-3", team="missing-team"))
    await save(engine, "assignments", {**assignment("user-1"), "id": "disabled", "enabled": False})
    await engine.repository.mutate(
        "organizations", "team-1", {**organization("team-1"), "enabled": False}, {"id": "audit"}
    )
    with pytest.raises(ValueError, match="enabled team"):
        await save(engine, "assignments", assignment("user-4"))


async def test_teams_require_an_enabled_same_tenant_department(engine: Engine) -> None:
    with pytest.raises(ValueError, match="Team parent"):
        await save(engine, "organizations", organization("team-x", department="missing"))
    with pytest.raises(ValueError, match="Team parent"):
        await save(engine, "organizations", organization("team-x", department="team-1"))
    await engine.repository.create(
        "organizations", "dept-2", organization("dept-2", "department", tenant="tenant-2")
    )
    with pytest.raises(ValueError, match="Team parent"):
        await save(engine, "organizations", organization("team-x", department="dept-2"))

    await save(engine, "organizations", organization("dept-3", "department"))


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [("user", "nobody"), ("team", "missing-team"), ("department", "team-1")],
)
async def test_budgets_require_an_active_matching_subject(
    engine: Engine, subject_type: str, subject_id: str
) -> None:
    with pytest.raises(ValueError, match="active user or organization"):
        await save(engine, "budgets", budget(subject_type, subject_id))


async def test_budgets_are_bound_to_the_administrators_tenant(engine: Engine) -> None:
    with pytest.raises(ValueError, match="tenant must match"):
        await save(engine, "budgets", budget("user", "user-1", tenant="tenant-2"))

    saved = await save(engine, "budgets", budget("team", "team-1"))

    assert saved["subject_id"] == "team-1"


async def test_budget_status_hides_budgets_from_unassigned_users(engine: Engine) -> None:
    assert await engine.budget_status(TENANT, "stranger") == []
    assert len(await engine.budget_status(TENANT, "user-1")) == 3


async def test_budget_status_attributes_unassigned_teams_to_their_department(
    engine: Engine,
) -> None:
    await save(engine, "organizations", organization("team-2"))
    await save(engine, "budgets", budget("team", "team-2"))

    with patch("apim_rate_limit_foundry.engine.report_service.emit") as emit:
        rows = await engine.budget_status(TENANT, "admin", admin=True)

    assert "budget-team-2" in {row["budget_id"] for row in rows}
    team_two = next(c for c in emit.call_args_list if c.kwargs["subject_id"] == "team-2")
    assert team_two.kwargs["team_id"] == "team-2"
    assert team_two.kwargs["department_id"] == "department-1"
