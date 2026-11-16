"""Configuration collections and schema markers shared by engine services."""

from apim_rate_limit_foundry.models import Assignment, Budget, Organization, Price
from apim_rate_limit_foundry.stores.contracts import Record

CONFIG_MODELS: dict[str, type[Organization] | type[Assignment] | type[Budget] | type[Price]] = {
    "organizations": Organization,
    "assignments": Assignment,
    "budgets": Budget,
    "prices": Price,
}
CURRENT_SCHEMA_MARKERS = {
    "organizations": "kind",
    "assignments": "principal_id",
    "budgets": "subject_type",
    "prices": "input_per_million",
}
USAGE_COLLECTION = "usage_v2"
LEGACY_FIELDS = {"prices": {"service", "per_page", "per_text_record", "per_request"}}


def is_legacy(collection: str, record: Record) -> bool:
    """Treat records from an archived schema as legacy data.

    A record is legacy when it lacks the current schema's identifying field or
    carries a field only the archived multi-service schema used.
    """
    if CURRENT_SCHEMA_MARKERS[collection] not in record:
        return True
    return not LEGACY_FIELDS.get(collection, set()).isdisjoint(record)
