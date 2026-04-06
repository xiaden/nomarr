"""Tests for static AQL read/write conflict detection."""

from __future__ import annotations

import pytest

from .conftest import (
    _PRODUCTION_ROOT,
    _SCRIPTS_ROOT,
    _find_read_write_conflicts,
    _find_violations,
    _format_violations,
)


class TestFindReadWriteConflicts:
    """Unit tests for the _find_read_write_conflicts detection function."""

    @pytest.mark.unit
    def test_pattern_a_flags_let_read_then_insert_same_collection(self) -> None:
        """Pattern A: LET-read + INSERT on the same collection name is flagged."""
        aql = "LET x = (FOR d IN my_coll RETURN d) INSERT {_key:'k'} INTO my_coll"
        assert _find_read_write_conflicts(aql) == {"my_coll"}

    @pytest.mark.unit
    def test_pattern_b_flags_for_remove_insert_same_collection(self) -> None:
        """Pattern B: FOR + REMOVE + INSERT on the same collection is flagged."""
        aql = "FOR e IN edges REMOVE e IN edges INSERT {_from: e._from} INTO edges"
        assert _find_read_write_conflicts(aql) == {"edges"}

    @pytest.mark.unit
    def test_safe_read_only_query_not_flagged(self) -> None:
        """Read-only FOR loop is not flagged."""
        aql = "FOR e IN file_has_state FILTER e._from == @file_id RETURN e._key"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_safe_insert_only_not_flagged(self) -> None:
        """INSERT-only statement is not flagged."""
        aql = "INSERT { _from: @file_id, _to: @new_state } INTO file_has_state"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_safe_remove_only_not_flagged(self) -> None:
        """REMOVE-only statement is not flagged."""
        aql = "REMOVE @old_key IN file_has_state"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_empty_string_returns_empty_set(self) -> None:
        """Empty string produces no conflicts."""
        assert _find_read_write_conflicts("") == set()

    @pytest.mark.unit
    def test_different_collections_not_flagged(self) -> None:
        """LET-read on coll_a + INSERT into coll_b is safe."""
        aql = "LET x = (FOR d IN coll_a RETURN d) INSERT {_key:'k'} INTO coll_b"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_pattern_b_for_remove_no_insert_not_flagged(self) -> None:
        """FOR + REMOVE without INSERT is safe (single-pass delete)."""
        aql = "FOR e IN edges REMOVE e IN edges"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_returns_multiple_conflicting_collections(self) -> None:
        """Multiple conflicting collection names are all returned."""
        aql = (
            "LET x = (FOR d IN coll_a RETURN d) INSERT {_key:'k'} INTO coll_a "
            "LET y = (FOR d IN coll_b RETURN d) INSERT {_key:'k'} INTO coll_b"
        )
        conflicts = _find_read_write_conflicts(aql)
        assert "coll_a" in conflicts
        assert "coll_b" in conflicts


@pytest.mark.unit
def test_no_mixed_read_write_aql_in_production_code() -> None:
    """Production Python code should not mix reads and writes on one collection."""
    violations = _find_violations(_PRODUCTION_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))


@pytest.mark.unit
@pytest.mark.xfail(
    strict=False,
    reason="scripts/ contains legacy dev tools with known mixed-AQL patterns",
)
def test_no_mixed_read_write_aql_in_scripts() -> None:
    """Advisory check for legacy scripts that still contain mixed-AQL patterns."""
    if not _SCRIPTS_ROOT.exists():
        pytest.skip("scripts/ directory does not exist")

    violations = _find_violations(_SCRIPTS_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))
