"""Tests for missing OPTIONS { ignoreErrors: true } on REMOVE operations."""

from __future__ import annotations

import re

import pytest

from .conftest import (
    _PERSISTENCE_DATABASE_ROOT,
    _scan_all_aql_strings,
    _strip_aql_comments,
)

_Violation = tuple[str, int, str]


def _find_remove_without_ignore_errors(aql: str) -> list[str]:
    """Return REMOVE statements that lack OPTIONS { ignoreErrors: true }.

    In cascade delete operations, REMOVE should include OPTIONS { ignoreErrors: true }
    to handle cases where documents may have already been deleted.
    """
    query = _strip_aql_comments(aql)

    # Pattern matches REMOVE ... IN collection without OPTIONS { ignoreErrors: true }
    # We need to check each REMOVE statement individually
    violations = []

    # Split by REMOVE keyword and check each one
    parts = re.split(r"\bREMOVE\b", query, flags=re.IGNORECASE)

    # Skip the first part (before any REMOVE)
    for _i, part in enumerate(parts[1:], start=1):
        # Get the REMOVE statement (up to the next major keyword or end)
        remove_stmt = re.split(
            r"\b(?:FOR|LET|INSERT|UPDATE|UPSERT|COLLECT|SORT|LIMIT|RETURN|FILTER)\b", part, flags=re.IGNORECASE
        )[0]

        # Check if this REMOVE has OPTIONS { ignoreErrors: true }
        if not re.search(r"OPTIONS\s*\{\s*ignoreErrors\s*:\s*true\s*\}", remove_stmt, re.IGNORECASE):
            # Extract the collection name for the error message
            match = re.search(r"IN\s+(@@\w+|\w+)", remove_stmt, re.IGNORECASE)
            collection = match.group(1) if match else "unknown"
            violations.append(f"REMOVE in {collection}")

    return violations


def _find_violations(root: type) -> list[_Violation]:
    """Find all REMOVE operations without OPTIONS { ignoreErrors: true }."""

    violations: list[_Violation] = []

    for file_path, line_number, aql in _scan_all_aql_strings(root):
        missing = _find_remove_without_ignore_errors(aql)
        violations.extend((file_path, line_number, desc) for desc in missing)

    return sorted(violations)


def _format_violations(violations: list[_Violation]) -> str:
    """Format violations into a human-readable message."""
    lines = ["REMOVE operations without OPTIONS { ignoreErrors: true }:"]
    lines.extend(f"- {file_path}:{line_number} -> {desc}" for file_path, line_number, desc in violations)
    return "\n".join(lines)


@pytest.mark.unit
def test_no_remove_without_ignore_errors_in_production_code() -> None:
    """Production Python code should include OPTIONS { ignoreErrors: true } on REMOVE operations."""
    violations = _find_violations(_PERSISTENCE_DATABASE_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))
