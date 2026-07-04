"""Tests for duplicate AQL variable names at the same scope level."""

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


def _find_top_level_variable_duplicates(aql: str) -> list[str]:
    """Return variable names that are assigned multiple times at the top scope level.

    In AQL, top-level FOR/LET/COLLECT statements share the same scope.
    Reusing a variable name at this level causes ERR 1511.

    This function tracks parenthesis depth to distinguish top-level
    statements from subqueries (which have their own scope).
    """
    query = _strip_aql_comments(aql)

    # Pattern matches FOR var IN, FOR var, var2 IN (multi-variable FOR),
    # LET var =, and COLLECT var =
    pattern = re.compile(
        r"(?:FOR\s+(\w+)(?:\s*,\s*(\w+))?\s+IN|LET\s+(\w+)\s*=|COLLECT\s+(\w+)\s*=)",
        re.IGNORECASE,
    )

    # Track parenthesis depth to identify top-level statements
    depth = 0
    top_level_vars: list[str] = []
    duplicates: set[str] = set()

    # Walk through the query, tracking depth and extracting variables
    last_end = 0
    for match in re.finditer(r"[()]", query):
        paren_pos = match.start()
        paren_char = match.group()

        # Process any variable declarations between last position and this paren
        segment = query[last_end:paren_pos]
        if depth == 0:
            # At top level, extract variables from this segment
            for var_match in pattern.finditer(segment):
                for group_idx in range(1, 5):
                    var_name = var_match.group(group_idx)
                    if var_name is not None:
                        var_lower = var_name.lower()
                        if var_lower in top_level_vars:
                            duplicates.add(var_lower)
                        else:
                            top_level_vars.append(var_lower)

        # Update depth
        if paren_char == "(":
            depth += 1
        elif paren_char == ")":
            depth = max(0, depth - 1)

        last_end = paren_pos + 1

    # Process the final segment after the last parenthesis
    final_segment = query[last_end:]
    if depth == 0:
        for var_match in pattern.finditer(final_segment):
            for group_idx in range(1, 5):
                var_name = var_match.group(group_idx)
                if var_name is not None:
                    var_lower = var_name.lower()
                    if var_lower in top_level_vars:
                        duplicates.add(var_lower)
                    else:
                        top_level_vars.append(var_lower)

    return sorted(duplicates)


def _find_duplicate_variable_violations(
    root: Path,
) -> list[_Violation]:
    """Return all duplicate variable name violations under a directory tree."""
    violations: list[_Violation] = []

    for file_path, line_number, aql in _scan_all_aql_strings(root):
        duplicates = _find_top_level_variable_duplicates(aql)
        violations.extend((file_path, line_number, var_name) for var_name in duplicates)

    return sorted(violations)


def _format_duplicate_variable_violations(violations: list[_Violation]) -> str:
    """Return a human-readable failure message for duplicate variable violations."""
    lines = ["Duplicate AQL variable names at top scope level (causes ERR 1511):"]
    lines.extend(
        f"- {file_path}:{line_number} -> variable '{var_name}'" for file_path, line_number, var_name in violations
    )
    lines.append("\nIn AQL, top-level FOR/LET/COLLECT statements share the same scope.")
    lines.append("Each variable name must be unique at the top level of a query.")
    lines.append("Use different variable names or wrap in subqueries with LET.")
    return "\n".join(lines)


class TestFindTopLevelVariableDuplicates:
    """Unit tests for the _find_top_level_variable_duplicates function."""

    @pytest.mark.unit
    def test_single_for_loop_no_duplicates(self) -> None:
        """Single FOR loop has no duplicates."""
        aql = "FOR e IN edges FILTER e._from == @id RETURN e"
        assert _find_top_level_variable_duplicates(aql) == []

    @pytest.mark.unit
    def test_different_variable_names_no_duplicates(self) -> None:
        """Multiple FOR loops with different variable names are safe."""
        aql = "FOR e IN edges FILTER e._from == @id REMOVE e IN edges FOR f IN files RETURN f"
        assert _find_top_level_variable_duplicates(aql) == []

    @pytest.mark.unit
    def test_duplicate_for_variable_flagged(self) -> None:
        """Reusing the same variable name in top-level FOR loops is flagged."""
        aql = "FOR e IN edges REMOVE e IN edges FOR e IN files RETURN e"
        assert _find_top_level_variable_duplicates(aql) == ["e"]

    @pytest.mark.unit
    def test_multiple_duplicates_flagged(self) -> None:
        """Multiple duplicate variable names are all flagged."""
        aql = "FOR e IN edges REMOVE e IN edges FOR e IN files RETURN e FOR e IN docs RETURN e"
        assert _find_top_level_variable_duplicates(aql) == ["e"]

    @pytest.mark.unit
    def test_let_variable_duplicate_flagged(self) -> None:
        """Reusing a LET variable name at top level is flagged."""
        aql = "LET x = 1 LET x = 2 RETURN x"
        assert _find_top_level_variable_duplicates(aql) == ["x"]

    @pytest.mark.unit
    def test_for_and_let_same_name_flagged(self) -> None:
        """FOR and LET using the same variable name at top level is flagged."""
        aql = "LET e = 1 FOR e IN edges RETURN e"
        assert _find_top_level_variable_duplicates(aql) == ["e"]

    @pytest.mark.unit
    def test_subquery_variable_not_flagged(self) -> None:
        """Variables in subqueries don't conflict with top-level variables."""
        aql = "LET x = (FOR e IN edges RETURN e) FOR e IN files RETURN e"
        assert _find_top_level_variable_duplicates(aql) == []

    @pytest.mark.unit
    def test_nested_subquery_variables_not_flagged(self) -> None:
        """Variables in nested subqueries don't conflict with outer scopes."""
        aql = "LET x = (FOR e IN edges RETURN (FOR e IN files RETURN e)) FOR e IN docs RETURN e"
        assert _find_top_level_variable_duplicates(aql) == []

    @pytest.mark.unit
    def test_case_insensitive_duplicate_detection(self) -> None:
        """Variable names are case-insensitive (AQL is case-insensitive for vars)."""
        aql = "FOR e IN edges REMOVE e IN edges FOR E IN files RETURN E"
        assert _find_top_level_variable_duplicates(aql) == ["e"]

    @pytest.mark.unit
    def test_multi_variable_for_loop(self) -> None:
        """Multi-variable FOR loops (FOR v, e IN) are checked correctly."""
        aql = "FOR v, e IN OUTBOUND start edges FOR v, e IN OUTBOUND start2 edges"
        assert _find_top_level_variable_duplicates(aql) == ["e", "v"]

    @pytest.mark.unit
    def test_collect_variable_duplicate_flagged(self) -> None:
        """COLLECT variable name duplicates are flagged."""
        aql = "FOR d IN docs COLLECT category = d.category RETURN category FOR category IN cats RETURN category"
        # Note: COLLECT category = assigns to 'category', then FOR category reuses it
        # This should be flagged
        result = _find_top_level_variable_duplicates(aql)
        assert "category" in result

    @pytest.mark.unit
    def test_empty_query_returns_empty(self) -> None:
        """Empty query returns no duplicates."""
        assert _find_top_level_variable_duplicates("") == []

    @pytest.mark.unit
    def test_comments_ignored(self) -> None:
        """Variables in AQL comments are ignored."""
        aql = "FOR e IN edges RETURN e // FOR e IN files RETURN e"
        assert _find_top_level_variable_duplicates(aql) == []

    @pytest.mark.unit
    def test_real_world_libraries_delete_query(self) -> None:
        """Test the actual pattern from libraries_aql.py that caused the bug."""
        aql = """
            LET file_ids = (
                FOR e IN library_contains_file
                    FILTER e._from == @lib
                    RETURN e._to
            )
            LET stream_ids = (
                FOR e IN file_has_output_stream
                    FILTER e._from IN file_ids
                    RETURN e._to
            )
            FOR e IN output_has_stream
                FILTER e._to IN stream_ids
                REMOVE e IN output_has_stream
            FOR sid IN stream_ids
                REMOVE sid IN ml_output_streams OPTIONS { ignoreErrors: true }
            FOR e IN file_has_output_stream
                FILTER e._from IN file_ids
                REMOVE e IN file_has_output_stream
            FOR e IN file_has_vectors
                FILTER e._from IN file_ids
                REMOVE e IN file_has_vectors
        """
        # 'e' is used in multiple top-level FOR loops
        assert "e" in _find_top_level_variable_duplicates(aql)


@pytest.mark.unit
def test_no_duplicate_top_level_variables_in_persistence_aql() -> None:
    """All persistence AQL queries must use unique variable names at top scope level.

    ArangoDB ERR 1511: variable '<name>' is assigned multiple times.
    This occurs when top-level FOR/LET/COLLECT statements reuse variable names.
    """
    violations = _find_duplicate_variable_violations(_PERSISTENCE_DATABASE_ROOT)
    if violations:
        pytest.fail(_format_duplicate_variable_violations(violations))
