#!/usr/bin/env python3
# noqa: N999
"""Validate the ArangoDB field name allowlist.

Loads .arango-field-allowlist.yaml from the repository root, checks that every
entry has the required fields (file, line, field, expiry, reason), and verifies
that no entry has expired.

Exit codes:
    0 — all entries are valid and not expired
    1 — one or more entries are expired or malformed
"""

import sys
from datetime import date
from pathlib import Path

import yaml

REQUIRED_FIELDS = {"file", "line", "field", "expiry", "reason"}

# Resolve allowlist path relative to this script's location (scripts/ → repo root)
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_ALLOWLIST_PATH = _REPO_ROOT / ".arango-field-allowlist.yaml"


def main() -> int:
    if not _ALLOWLIST_PATH.exists():
        print(f"ERROR: Allowlist not found at {_ALLOWLIST_PATH}", file=sys.stderr)
        return 1

    try:
        with open(_ALLOWLIST_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        print(f"ERROR: Malformed YAML in allowlist: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict) or "violations" not in data:
        print("ERROR: Allowlist must contain a 'violations' list", file=sys.stderr)
        return 1

    violations = data["violations"]
    if not isinstance(violations, list):
        print("ERROR: 'violations' must be a list", file=sys.stderr)
        return 1

    today = date.today()
    valid_count = 0
    expired_entries: list[dict] = []
    malformed_entries: list[dict] = []

    for idx, entry in enumerate(violations):
        if not isinstance(entry, dict):
            malformed_entries.append({"index": idx, "reason": "entry is not a mapping"})
            continue

        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            malformed_entries.append({"index": idx, "reason": f"missing fields: {', '.join(sorted(missing))}"})
            continue

        # Parse expiry
        try:
            expiry_date = date.fromisoformat(str(entry["expiry"]))
        except (ValueError, TypeError) as exc:
            malformed_entries.append({"index": idx, "reason": f"invalid expiry date: {entry['expiry']!r} ({exc})"})
            continue

        if expiry_date < today:
            expired_entries.append(
                {
                    "file": entry["file"],
                    "line": entry["line"],
                    "field": entry["field"],
                    "expiry": str(entry["expiry"]),
                }
            )
        else:
            valid_count += 1

    # Report malformed entries first
    if malformed_entries:
        print(f"ERROR: {len(malformed_entries)} malformed entries:", file=sys.stderr)
        for item in malformed_entries:
            print(f"  [{item['index']}] {item['reason']}", file=sys.stderr)

    # Report summary
    print(f"{valid_count} entries valid, {len(expired_entries)} entries expired")

    # Report expired entries
    if expired_entries:
        print("\nExpired entries:", file=sys.stderr)
        for item in expired_entries:
            print(
                f"  {item['file']}:{item['line']} (field={item['field']}, expired={item['expiry']})",
                file=sys.stderr,
            )

    if malformed_entries or expired_entries:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
