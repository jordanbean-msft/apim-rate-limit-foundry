"""Explicit configuration-only migration from user-scoped to app-scoped records."""

from typing import Any

from apim_rate_limit_foundry.models.assignment import Assignment
from apim_rate_limit_foundry.models.policy import Policy

Record = dict[str, Any]


def migrate_application_configuration(
    policies: list[Record],
    assignments: list[Record],
    mapping: dict[str, dict[str, str]],
) -> tuple[list[Record], list[Record]]:
    """Convert legacy records only when each has an explicit subscription mapping."""
    if set(mapping) != {"policies", "assignments"}:
        raise ValueError("Mapping must contain exactly policies and assignments")
    migrated_policies = _migrate_collection(policies, mapping["policies"], "policies")
    migrated_assignments = _migrate_collection(assignments, mapping["assignments"], "assignments")
    return migrated_policies, migrated_assignments


def _migrate_collection(
    records: list[Record],
    collection_mapping: dict[str, str],
    collection: str,
) -> list[Record]:
    record_ids = [record.get("id") for record in records]
    if not all(isinstance(record_id, str) for record_id in record_ids) or len(
        set(record_ids)
    ) != len(records):
        raise ValueError(f"{collection} records must have unique string IDs")

    legacy = {record["id"] for record in records if not record.get("subscription_id")}
    if legacy != set(collection_mapping):
        raise ValueError(
            f"{collection} mapping must explicitly cover every legacy record and no others"
        )

    result: list[Record] = []
    for record in records:
        if record.get("subscription_id"):
            if "principal_id" in record:
                raise ValueError(f"{collection} record mixes old and new identity fields")
            if collection == "policies":
                Policy.model_validate(record)
            else:
                Assignment.model_validate(record)
            result.append(dict(record))
            continue
        else:
            if "principal_id" not in record:
                raise ValueError(
                    f"{collection} record {record['id']} lacks both subscription and actor identity"
                )
            subscription_id = collection_mapping[record["id"]]
            if subscription_id == "*":
                raise ValueError("Legacy records must map to a concrete application subscription")
            migrated = {**record, "subscription_id": subscription_id}
            actor = migrated.pop("principal_id")
            if collection == "assignments":
                if actor == "*":
                    raise ValueError("Wildcard assignment owners cannot become Reader grants")
                if "reader_principal_ids" in migrated:
                    raise ValueError("Legacy assignment already contains a Reader list")
                migrated["reader_principal_ids"] = [actor]
        if collection == "policies":
            result.append(Policy.model_validate(migrated).model_dump(mode="json"))
        else:
            result.append(Assignment.model_validate(migrated).model_dump(mode="json"))
    return result
