"""The only event names and attributes allowed to leave the process.

Anything not listed here is rewritten to ``application_event`` or dropped, so a
new ``emit()`` event or field must be added here (and kept free of prompts,
credentials and raw identities) before it can reach logs or Application Insights.
"""

FALLBACK_EVENT = "application_event"

# Correlation and trace identity.
_IDENTITY_FIELDS = {
    "correlation_id",
    "request_id",
    "trace_id",
    "span_id",
    "event_name",
    "event_version",
    "event_id",
}
# Pseudonymous attribution; raw tenant/user identifiers are never allowlisted.
_ATTRIBUTION_FIELDS = {
    "tenant_ref",
    "user_ref",
    "team_id",
    "department_id",
    "business_unit",
    "cost_center",
    "subscription_id",
}
_BUDGET_FIELDS = {
    "budget_id",
    "budget_ids",
    "budget_model",
    "budget_count",
    "denied_budget_count",
    "denied_budget_ids",
    "subject_type",
    "subject_id",
    "month",
    "limit_micro_usd",
    "spent_micro_usd",
    "remaining_micro_usd",
    "allowed",
    "reason",
    "retry_after",
    "reset_at",
}
_USAGE_FIELDS = {
    "model",
    "api_protocol",
    "streaming",
    "price_version",
    "cost_micro_usd",
    "cost_basis",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "total_tokens",
    "cache_hit",
    "out_of_bounds",
    "replayed",
}
_OPERATION_FIELDS = {
    "operation",
    "dependency",
    "status",
    "error_type",
    "duration_ms",
    "http_method",
    "http_status",
    "route",
    "collection",
    "record_id",
    "action",
    "pending",
    "records",
}

FIELDS = frozenset(
    _IDENTITY_FIELDS | _ATTRIBUTION_FIELDS | _BUDGET_FIELDS | _USAGE_FIELDS | _OPERATION_FIELDS
)
# Free text accepted with a length/character check instead of the strict identifier pattern.
TEXT_FIELDS = frozenset({"route", "reset_at", "month", "business_unit", "cost_center"})
LIST_FIELDS = frozenset({"budget_ids", "denied_budget_ids"})

EVENTS = frozenset(
    {
        FALLBACK_EVENT,
        # Process lifecycle.
        "telemetry_initialized",
        "runtime_closed",
        # Requests, operations and dependencies.
        "request_started",
        "request_completed",
        "request_failed",
        "request_rejected",
        "operation_started",
        "operation_completed",
        "operation_failed",
        "dependency_completed",
        "limiter_dependency_unavailable",
        "metric_record_failed",
        # Budget decisions and balances.
        "budget_decision",
        "budget_evaluated",
        "budget_status",
        # Usage accounting.
        "usage_recorded",
        "usage_record_replayed",
        "usage_record_failed",
        "usage_out_of_bounds",
        "usage_event_publish_accepted",
        "usage_event_publish_failed",
        # Streaming.
        "stream_usage_unknown",
        "stream_rejected_by_provider",
        # Durable records and configuration.
        "configuration_written",
        "configuration_cache_loaded",
        "configuration_record_invalid",
        "durable_record_read",
        "durable_record_replayed",
        # Best-effort background writes.
        "background_write_completed",
        "background_write_failed",
        "background_write_dropped",
        "background_worker_failed",
        "background_writes_abandoned",
        # Dashboard.
        "dashboard_timeout",
        "dashboard_unavailable",
        "dashboard_query_failed",
    }
)
