from datetime import UTC, datetime

import pytest

from apim_rate_limit_foundry.accounting import cost, matching, validate_estimate, window
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import Assignment, Policy, Price, Reserve, Usage


def test_cached_prices_are_only_used_for_actual(price: Price) -> None:
    usage = Usage(input_tokens=10, output_tokens=2, cached_input_tokens=8)
    assert cost(price, usage, True) == 28
    assert cost(price, usage, False) == 16
    fractional = price.model_copy(update={"input_per_million": price.input_per_million / 3})
    assert cost(fractional, Usage(input_tokens=1, requests=0), False) == 1


def test_unknown_price_and_invalid_cached_subset(price: Price) -> None:
    with pytest.raises(ValueError, match="Unknown"):
        cost(
            price.model_copy(update={"cached_input_per_million": None}),
            Usage(input_tokens=1, cached_input_tokens=1),
            False,
        )
    with pytest.raises(ValueError, match="subset"):
        Usage(input_tokens=1, cached_input_tokens=2)


def test_conservative_price_covers_more_expensive_cached_tokens(price: Price) -> None:
    price.cached_input_per_million = price.output_per_million
    usage = Usage(input_tokens=10, output_tokens=1, cached_input_tokens=10)
    assert cost(price, usage, True) >= cost(price, usage, False)


def test_price_catalog_rejects_binary_floating_point(price: Price) -> None:
    with pytest.raises(ValueError, match="decimal USD strings"):
        Price.model_validate({**price.model_dump(), "input_per_million": 0.1})


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("minute", "2024-02-29T23:59:00+00:00", "2024-03-01T00:00:00+00:00"),
        ("hour", "2024-02-29T23:00:00+00:00", "2024-03-01T00:00:00+00:00"),
        ("day", "2024-02-29T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
        ("month", "2024-02-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
    ],
)
def test_utc_window_boundaries(period: str, start: str, end: str) -> None:
    result = window(period, datetime(2024, 2, 29, 23, 59, 59, tzinfo=UTC))
    assert tuple(t.isoformat() for t in result) == (start, end)


def test_assignments_are_tenant_principal_scoped(request_body: Reserve, policy: Policy) -> None:
    assignment = Assignment(
        id="a", tenant_id="other-tenant", principal_id="user-1", policy_ids=[policy.id]
    )
    assert matching(request_body, [policy], [assignment]) == []
    assignment.tenant_id = request_body.tenant_id
    high_priority = policy.model_copy(update={"id": "p2", "priority": 20})
    assert matching(request_body, [policy, high_priority], [assignment]) == [high_priority, policy]
    assert matching(request_body, [policy.model_copy(update={"tenant_id": "other"})], []) == []


def test_service_estimates_are_hard_bounded(settings: Settings, request_body: Reserve) -> None:
    with pytest.raises(ValueError, match="Token bound"):
        validate_estimate(
            request_body.model_copy(
                update={
                    "usage": Usage(input_tokens=1, output_tokens=settings.max_output_tokens + 1)
                }
            ),
            settings,
        )
    with pytest.raises(ValueError, match="predicted"):
        validate_estimate(
            request_body.model_copy(
                update={"usage": Usage(input_tokens=10, output_tokens=1, cached_input_tokens=1)}
            ),
            settings,
        )
    document = request_body.model_copy(
        update={
            "service": "document-intelligence",
            "usage": Usage(pages=2),
        }
    )
    with pytest.raises(ValueError, match="verified"):
        validate_estimate(document, settings)
    validate_estimate(document.model_copy(update={"document_bound_verified": True}), settings)
    validate_estimate(
        request_body.model_copy(
            update={
                "service": "language",
                "usage": Usage(text_records=2),
            }
        ),
        settings,
    )
