import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models import Policy, Price, Reserve, Usage
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, local_auth_enabled=True, local_store_enabled=True)


@pytest.fixture
def request_body() -> Reserve:
    return Reserve(
        request_id="request-1",
        tenant_id="tenant-1",
        principal_id="user-1",
        service="foundry",
        model="model-1",
        operation="chat",
        usage=Usage(input_tokens=10, output_tokens=20),
    )


@pytest.fixture
def price() -> Price:
    return Price(
        id="price-1",
        service="foundry",
        model="model-1",
        version="v1",
        input_per_million="2",
        output_per_million="4",
        cached_input_per_million="0.5",
        per_request="0",
    )


@pytest.fixture
def policy() -> Policy:
    return Policy(
        id="policy-1", name="Budget", service="foundry", limit=300, period="day", metric="cost"
    )


@pytest.fixture
async def engine(settings: Settings, price: Price, policy: Policy) -> Engine:
    repository = MemoryRepository()
    await repository.create("prices", price.id, price.model_dump(mode="json"))
    await repository.create("policies", policy.id, policy.model_dump(mode="json"))
    return Engine(repository, MemoryCounters(), settings)
