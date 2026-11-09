import pytest
from pydantic import ValidationError

from apim_rate_limit_foundry.models import Assignment, Budget, BudgetCheck, Organization, Price


def test_organization_and_assignment_contracts_require_hierarchy() -> None:
    with pytest.raises(ValidationError, match="Teams must reference"):
        Organization(
            id="team",
            tenant_id="tenant",
            kind="team",
            name="Platform",
            business_unit="BU",
            cost_center="CC",
        )
    with pytest.raises(ValidationError, match="Departments cannot"):
        Organization(
            id="department",
            tenant_id="tenant",
            kind="department",
            name="Engineering",
            department_id="other",
            business_unit="BU",
            cost_center="CC",
        )
    assignment = Assignment(
        id="assignment",
        tenant_id="tenant",
        principal_id="user",
        team_id="team",
        department_id="department",
    )
    assert assignment.enabled


def test_budget_uses_nonnegative_integer_micro_usd_and_monthly_scope() -> None:
    budget = Budget(
        id="budget",
        tenant_id="tenant",
        name="Monthly",
        subject_type="department",
        subject_id="engineering",
        limit_micro_usd=0,
    )
    assert budget.limit_micro_usd == 0
    with pytest.raises(ValidationError):
        Budget(
            id="bad-budget",
            tenant_id="tenant",
            name="Bad",
            subject_type="team",
            subject_id="team",
            limit_micro_usd=1.5,
        )


def test_price_contract_is_openai_token_only_and_decimal_string_based() -> None:
    price = Price(
        id="price",
        model="model",
        version="v1",
        input_per_million="1.25",
        cached_input_per_million="0.5",
        output_per_million="3",
    )
    assert price.model_dump(mode="json")["input_per_million"] == "1.25"
    with pytest.raises(ValidationError):
        Price(
            id="price",
            model="model",
            version="v1",
            input_per_million=1.25,
            cached_input_per_million="0.5",
            output_per_million="3",
        )
    with pytest.raises(ValidationError):
        Price(
            id="price",
            model="model",
            version="v1",
            input_per_million="1",
            cached_input_per_million="0.5",
            output_per_million="3",
            per_page="0.1",
        )


def test_gateway_budget_check_has_no_predicted_usage_fields() -> None:
    body = BudgetCheck(
        request_id="r-1",
        tenant_id="tenant",
        principal_id="user",
        subscription_id="app",
        model="gpt",
        api_protocol="openai-responses",
        streaming=True,
    )
    assert body.streaming
    with pytest.raises(ValidationError):
        BudgetCheck.model_validate({**body.model_dump(), "predicted_cost": 42})
