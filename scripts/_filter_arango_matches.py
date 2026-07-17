#!/usr/bin/env python3
"""Filter ripgrep JSON output against the ArangoDB field name allowlist.

Reads ripgrep --json output from stdin, parses the YAML allowlist to get
allowed (file, line) pairs, and reports any matches that are NOT allowlisted.

Exit codes:
    0 — all matches are allowlisted (or no matches at all)
    1 — new violations found (not in allowlist)

Usage:
    rg --json 'pattern' | python3 scripts/_filter_arango_matches.py --allowlist .arango-field-allowlist.yaml
"""

import argparse
import json
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter ripgrep JSON against an ArangoDB field allowlist")
    parser.add_argument(
        "--allowlist",
        default=".arango-field-allowlist.yaml",
        help="Path to the YAML allowlist file (default: .arango-field-allowlist.yaml)",
    )
    return parser.parse_args()


def load_allowlist_pairs(allowlist_path: str) -> set[str]:
    """Load the allowlist and return a set of 'file:line' strings."""
    path = Path(allowlist_path)
    if not path.exists():
        print(f"ERROR: Allowlist file not found: {allowlist_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        print(f"ERROR: Malformed YAML in allowlist: {exc}", file=sys.stderr)
        sys.exit(1)

    if not data or "violations" not in data or not data["violations"]:
        return set()

    pairs: set[str] = set()
    for v in data["violations"]:
        pairs.add(f"{v['file']}:{v['line']}")
    return pairs


def filter_matches(allowlist_set: set[str]) -> int:
    """Read ripgrep JSON from stdin, filter against allowlist, report results.

    Returns exit code: 1 if new violations found, 0 otherwise.
    """
    rg_output = sys.stdin.read()
    new_violations: list[tuple[str, int, str]] = []
    total_matches = 0

    for line in rg_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") != "match":
            continue

        total_matches += 1
        data = obj["data"]
        file_path = data["path"]["text"]
        line_number = data["line_number"]
        matched_text = data["lines"]["text"].rstrip()

        pair = f"{file_path}:{line_number}"
        if pair not in allowlist_set:
            new_violations.append((file_path, line_number, matched_text))

    if new_violations:
        print(f"FOUND {len(new_violations)} NEW VIOLATION(S) NOT IN ALLOWLIST:")
        print()
        for file_path, line_number, matched_text in new_violations:
            print(f"  {file_path}:{line_number}: {matched_text}")
        print()
        print(f"({total_matches} total matches scanned, {total_matches - len(new_violations)} allowlisted)")
        print()
        print("To fix: either remove the ArangoDB field reference from the code,")
        print("or add it to .arango-field-allowlist.yaml with an expiry date.")
        return 1
    print(f"All ArangoDB field name references are allowlisted. ({total_matches} matches filtered)")
    return 0


def main() -> int:
    args = parse_args()
    allowlist_set = load_allowlist_pairs(args.allowlist)
    return filter_matches(allowlist_set)


if __name__ == "__main__":
    sys.exit(main())
