"""Tests for inefficient existence check patterns in AQL."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .conftest import (
    _PERSISTENCE_DATABASE_ROOT,
    _scan_all_aql_strings,
    _strip_aql_comments,
)

_Violation = tuple[str, int, str]


def _find_inefficient_existence_checks(aql: str) -> list[str]:
    """Return existence check patterns that should use FIRST() instead of LENGTH().

    Pattern: LENGTH(FOR ... LIMIT 1 RETURN 1) == 0
    Should be: FIRST(FOR ... LIMIT 1 RETURN 1) == null

    FIRST() is more efficient because it stops after finding the first match,
    while LENGTH() must count all results (even with LIMIT 1, it's semantically clearer).
    """
    query = _strip_aql_comments(aql)

    # Pattern matches LENGTH(FOR ... LIMIT 1 RETURN 1) == 0
    pattern = re.compile(
        r"LENGTH\s*\(\s*FOR\s+.*?\bLIMIT\s+1\s+RETURN\s+1\s*\)\s*==\s*0",
        re.IGNORECASE | re.DOTALL,
    )

    violations = []
    for match in pattern.finditer(query):
        # Extract a snippet for context
        snippet = match.group(0)[:50] + "..." if len(match.group(0)) > 50 else match.group(0)
        violations.append(f"LENGTH(FOR...LIMIT 1) should be FIRST(FOR...LIMIT 1): {snippet}")

    return violations


def _find_violations(root: Path) -> list[_Violation]:
    """Find all inefficient existence check patterns."""
    violations: list[_Violation] = []

    for file_path, line_number, aql in _scan_all_aql_strings(root):
        inefficient = _find_inefficient_existence_checks(aql)
        violations.extend((file_path, line_number, desc) for desc in inefficient)

    return sorted(violations)


def _format_violations(violations: list[_Violation]) -> str:
    """Format violations into a human-readable message."""
    lines = ["Inefficient existence check patterns (use FIRST() instead of LENGTH()):"]
    lines.extend(f"- {file_path}:{line_number} -> {desc}" for file_path, line_number, desc in violations)
    return "\n".join(lines)


@pytest.mark.unit
def test_no_inefficient_existence_checks_in_production_code() -> None:
    """Production Python code should use FIRST() instead of LENGTH() for existence checks."""
    violations = _find_violations(_PERSISTENCE_DATABASE_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))
