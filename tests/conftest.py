import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Assignment, Budget, Organization, Price
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository


@pytest.fixture(autouse=True)
def disable_telemetry_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_ENABLED", "false")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)


@pytest.fixture
async def engine(settings: Settings) -> Engine:
    repository = MemoryRepository()
    await repository.create(
        "organizations",
        "department-1",
        Organization(
            id="department-1",
            tenant_id="tenant-1",
            kind="department",
            name="Engineering",
            business_unit="BU-ENG",
            cost_center="CC-100",
        ).model_dump(mode="json"),
    )
    await repository.create(
        "organizations",
        "team-1",
        Organization(
            id="team-1",
            tenant_id="tenant-1",
            kind="team",
            name="Platform",
            department_id="department-1",
            business_unit="BU-ENG",
            cost_center="CC-100",
        ).model_dump(mode="json"),
    )
    assignment = Assignment(
        id="assignment-1",
        tenant_id="tenant-1",
        principal_id="user-1",
        team_id="team-1",
        department_id="department-1",
    )
    await repository.create("assignments", assignment.id, assignment.model_dump(mode="json"))
    price = Price(
        id="price-1",
        model="model-1",
        version="v1",
        input_per_million="2",
        cached_input_per_million="0.5",
        output_per_million="4",
    )
    await repository.create("prices", price.id, price.model_dump(mode="json"))
    for subject_type, subject_id in (
        ("user", "user-1"),
        ("team", "team-1"),
        ("department", "department-1"),
    ):
        budget = Budget(
            id=f"budget-{subject_type}",
            tenant_id="tenant-1",
            name=f"{subject_type} budget",
            subject_type=subject_type,
            subject_id=subject_id,
            model="*",
            limit_micro_usd=100,
        )
        await repository.create("budgets", budget.id, budget.model_dump(mode="json"))
    return Engine(repository, MemoryCounters(), settings)
