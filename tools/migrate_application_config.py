#!/usr/bin/env python3
"""Preview or explicitly migrate policy and assignment JSON to app subscriptions."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apim_rate_limit_foundry.migration import migrate_application_configuration


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policies", required=True, type=Path)
    parser.add_argument("--assignments", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Back up then replace both files")
    parser.add_argument(
        "--acknowledge-legacy-liabilities",
        action="store_true",
        help="Confirm historical usage and unsettled liabilities remain legacy-scoped",
    )
    arguments = parser.parse_args()

    policies = read_json(arguments.policies)
    assignments = read_json(arguments.assignments)
    mapping = read_json(arguments.mapping)
    if not isinstance(policies, list) or not isinstance(assignments, list):
        parser.error("Policy and assignment JSON roots must be arrays")
    if not isinstance(mapping, dict) or not all(
        isinstance(value, dict) for value in mapping.values()
    ):
        parser.error("Mapping JSON must have policies and assignments ID maps")

    migrated_policies, migrated_assignments = migrate_application_configuration(
        policies, assignments, mapping
    )
    cutover = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "policies_file": str(arguments.policies),
        "assignments_file": str(arguments.assignments),
        "legacy_policy_records_mapped": len(mapping["policies"]),
        "legacy_assignment_records_mapped": len(mapping["assignments"]),
        "historical_usage_and_telemetry": (
            "Unchanged and excluded from application rollups/dashboards; historical application "
            "attribution is unavailable when subscription IDs were not recorded."
        ),
        "unsettled_legacy_liabilities": (
            "Not mapped to applications; preserved in the legacy counter namespace during "
            "recovery and settlement."
        ),
    }

    if not arguments.apply:
        print(
            json.dumps(
                {
                    "policies": migrated_policies,
                    "assignments": migrated_assignments,
                    "cutover": cutover,
                },
                indent=2,
            )
        )
        return 0
    if not arguments.acknowledge_legacy_liabilities:
        parser.error("--apply requires --acknowledge-legacy-liabilities")

    manifest = arguments.policies.parent / "application-accounting-cutover.json"
    backups = [
        path.with_name(f"{path.name}.pre-application-accounting.bak")
        for path in (arguments.policies, arguments.assignments)
    ]
    if manifest.exists() or any(path.exists() for path in backups):
        parser.error("Cutover manifest or backup already exists; refusing to overwrite")
    for source, backup in zip((arguments.policies, arguments.assignments), backups, strict=True):
        shutil.copy2(source, backup)

    write_json(arguments.policies, migrated_policies)
    write_json(arguments.assignments, migrated_assignments)
    write_json(manifest, cutover)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
