import logging

from apim_rate_limit_foundry.telemetry import SafeTelemetryFilter, safe_attributes, safe_event


def test_budget_and_usage_telemetry_is_structured_without_identity_or_payload() -> None:
    attributes = safe_attributes(
        {
            "event_name": "budget_status",
            "user_ref": "a" * 64,
            "team_id": "team-platform",
            "department_id": "dept-engineering",
            "budget_id": "budget-1",
            "month": "2030-01",
            "limit_micro_usd": 1_000,
            "spent_micro_usd": 500,
            "remaining_micro_usd": 500,
            "principal_id": "raw-user-id",
            "prompt": "private text",
        }
    )
    assert attributes["user_ref"] == "a" * 64
    assert attributes["spent_micro_usd"] == 500
    assert "principal_id" not in attributes
    assert "prompt" not in attributes


def test_safety_filter_drops_exception_text_and_unknown_fields() -> None:
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "usage_recorded", (), None)
    record.user_ref = "b" * 64
    record.principal_id = "private-user"
    record.prompt = "private prompt"
    record.exc_text = "secret exception detail"

    assert SafeTelemetryFilter().filter(record)
    assert record.user_ref == "b" * 64
    assert not hasattr(record, "principal_id")
    assert not hasattr(record, "prompt")
    assert record.exc_text is None


def test_new_budget_events_have_stable_names() -> None:
    assert safe_event("budget_decision") == "budget_decision"
    assert safe_event("usage_recorded") == "usage_recorded"
