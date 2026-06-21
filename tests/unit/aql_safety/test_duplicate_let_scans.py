"""Tests for duplicate LET scans on the same collection."""

from __future__ import annotations

import re
from collections import defaultdict

import pytest

from .conftest import (
    _PERSISTENCE_DATABASE_ROOT,
    _scan_all_aql_strings,
    _strip_aql_comments,
)

_Violation = tuple[str, int, str]


def _find_duplicate_let_scans(aql: str) -> list[str]:
    """Return collections that are scanned multiple times in LET statements with the same filter.

    Pattern: Multiple LET statements scanning the same collection with identical FILTER clauses.
    These should be consolidated into a single LET that returns both the IDs and edges.
    """
    query = _strip_aql_comments(aql)

    # Pattern matches LET var = (FOR e IN collection FILTER ... RETURN ...)
    let_pattern = re.compile(
        r"LET\s+(\w+)\s*=\s*\(\s*FOR\s+(\w+)\s+IN\s+(@@\w+|\w+)\s+FILTER\s+(.*?)\s+RETURN\s+(.*?)\s*\)",
        re.IGNORECASE | re.DOTALL,
    )

    # Track scans by collection and filter
    scans: dict[tuple[str, str], list[str]] = defaultdict(list)

    for match in let_pattern.finditer(query):
        var_name = match.group(1)
        collection = match.group(3)
        filter_clause = match.group(4).strip()
        match.group(5).strip()

        if collection == "__INTERPOLATION__":
            continue

        normalized_filter = re.sub(r"\s+", " ", filter_clause)

        key = (collection, normalized_filter)
        scans[key].append(var_name)

    # Find duplicates
    violations = []
    for (collection, _), var_names in scans.items():
        if len(var_names) > 1:
            violations.append(
                f"Collection '{collection}' scanned {len(var_names)} times with same filter "
                f"(variables: {', '.join(var_names)})"
            )

    return violations


def _find_violations(root: type) -> list[_Violation]:
    """Find all duplicate LET scans."""
    violations: list[_Violation] = []

    for file_path, line_number, aql in _scan_all_aql_strings(root):
        duplicates = _find_duplicate_let_scans(aql)
        violations.extend((file_path, line_number, desc) for desc in duplicates)

    return sorted(violations)


def _format_violations(violations: list[_Violation]) -> str:
    """Format violations into a human-readable message."""
    lines = ["Duplicate LET scans on same collection with same filter (should be consolidated):"]
    lines.extend(f"- {file_path}:{line_number} -> {desc}" for file_path, line_number, desc in violations)
    return "\n".join(lines)


@pytest.mark.unit
@pytest.mark.slow
def test_no_duplicate_let_scans_in_production_code() -> None:
    """Production Python code should not scan the same collection multiple times in LET statements."""
    violations = _find_violations(_PERSISTENCE_DATABASE_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))
