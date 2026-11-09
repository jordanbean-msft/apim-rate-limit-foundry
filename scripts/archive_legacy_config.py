"""Archive an exported legacy JSON ledger without changing ownership or values."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def archive(source: Path, destination: Path) -> None:
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict | list):
        raise ValueError("An exported JSON object or array is required")
    record = {
        "archive_version": 1,
        "archived_at": datetime.now(UTC).isoformat(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "accounting_scope": "legacy-unmodified",
        "data": payload,
    }
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive(args.input, args.output)


if __name__ == "__main__":
    main()
