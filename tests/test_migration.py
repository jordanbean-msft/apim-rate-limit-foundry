import copy

import pytest

from apim_rate_limit_foundry.migration import migrate_application_configuration


def test_migration_requires_explicit_concrete_subscription_mapping() -> None:
    policies = [
        {
            "id": "legacy-policy",
            "name": "Legacy budget",
            "service": "foundry",
            "model": "model-1",
            "principal_id": "user-1",
            "limit": 100,
            "period": "day",
            "metric": "cost",
        }
    ]
    assignments = [
        {
            "id": "legacy-assignment",
            "tenant_id": "tenant-1",
            "principal_id": "user-1",
            "policy_ids": ["legacy-policy"],
        }
    ]
    original = copy.deepcopy((policies, assignments))
    mapping = {
        "policies": {"legacy-policy": "app-1"},
        "assignments": {"legacy-assignment": "app-1"},
    }

    migrated_policies, migrated_assignments = migrate_application_configuration(
        policies, assignments, mapping
    )

    assert "principal_id" not in migrated_policies[0]
    assert migrated_policies[0]["subscription_id"] == "app-1"
    assert "principal_id" not in migrated_assignments[0]
    assert migrated_assignments[0]["subscription_id"] == "app-1"
    assert migrated_assignments[0]["reader_principal_ids"] == ["user-1"]
    assert (policies, assignments) == original
    with pytest.raises(ValueError, match="explicitly cover"):
        migrate_application_configuration(
            policies,
            assignments,
            {"policies": {}, "assignments": {"legacy-assignment": "app-1"}},
        )
    with pytest.raises(ValueError, match="concrete"):
        migrate_application_configuration(
            policies,
            assignments,
            {
                "policies": {"legacy-policy": "*"},
                "assignments": {"legacy-assignment": "app-1"},
            },
        )


def test_migration_refuses_wildcard_assignment_readers_and_preserves_new_records() -> None:
    with pytest.raises(ValueError, match="Wildcard assignment owners"):
        migrate_application_configuration(
            [],
            [
                {
                    "id": "legacy-assignment",
                    "tenant_id": "tenant-1",
                    "principal_id": "*",
                    "policy_ids": [],
                }
            ],
            {"policies": {}, "assignments": {"legacy-assignment": "app-1"}},
        )

    new_policy = {
        "id": "new-policy",
        "name": "App budget",
        "tenant_id": "tenant-1",
        "subscription_id": "app-1",
        "service": "foundry",
        "model": "model-1",
        "limit": 100,
        "period": "day",
        "metric": "cost",
    }
    migrated, assignments = migrate_application_configuration(
        [new_policy], [], {"policies": {}, "assignments": {}}
    )
    assert migrated == [new_policy]
    assert assignments == []
