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
    def test_upsert_insert_branch_not_flagged_as_standalone_write(self) -> None:
        """Pattern B: INSERT inside a UPSERT block is atomic and must not be flagged as a standalone write conflict."""
        aql = "FOR e IN edges UPSERT {_key: e._key} INSERT {_from: e._from, _to: e._to} UPDATE {} IN edges"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_for_remove_upsert_same_collection_flagged_by_pattern_c(self) -> None:
        """FOR + REMOVE + UPSERT on same collection is flagged (UPSERT reads after REMOVE writes)."""
        aql = (
            "FOR e IN edges REMOVE e IN edges "
            "UPSERT {_key: e._key} INSERT {_from: e._from, _to: e._to} UPDATE {} IN edges"
        )
        assert _find_read_write_conflicts(aql) == {"edges"}

    @pytest.mark.unit
    def test_standalone_insert_after_upsert_block_still_flagged(self) -> None:
        """Pattern B: a standalone INSERT after the UPSERT block on the same collection is still flagged."""
        aql = (
            "FOR e IN edges REMOVE e IN edges "
            "UPSERT {_key: e._key} INSERT {_from: e._from, _to: e._to} UPDATE {} IN edges "
            "INSERT {_from: 'x', _to: 'y'} INTO edges"
        )
        assert _find_read_write_conflicts(aql) == {"edges"}

    @pytest.mark.unit
    def test_pattern_c_flags_remove_then_upsert_same_collection(self) -> None:
        """Pattern C: REMOVE + UPSERT on the same collection triggers ERR 1579."""
        aql = (
            "FOR e IN file_has_vectors "
            "FILTER e._to == 'hot_id' "
            "REMOVE e IN file_has_vectors "
            "UPSERT { _from: 'f', _to: 'c' } "
            "INSERT { _from: 'f', _to: 'c' } "
            "UPDATE {} "
            "IN file_has_vectors"
        )
        assert _find_read_write_conflicts(aql) == {"file_has_vectors"}

    @pytest.mark.unit
    def test_pattern_c_remove_upsert_different_collections_safe(self) -> None:
        """Pattern C: REMOVE on coll_a + UPSERT on coll_b is safe."""
        aql = "FOR e IN coll_a REMOVE e IN coll_a UPSERT { _key: 'k' } INSERT { v: 1 } UPDATE { v: 1 } IN coll_b"
        assert _find_read_write_conflicts(aql) == set()

    @pytest.mark.unit
    def test_pattern_c_upsert_only_not_flagged(self) -> None:
        """Pattern C: standalone UPSERT without REMOVE is safe."""
        aql = "UPSERT { _from: @fid, _to: @vid } INSERT { _from: @fid, _to: @vid } UPDATE {} IN file_has_vectors"
        assert _find_read_write_conflicts(aql) == set()


@pytest.mark.unit
def test_no_mixed_read_write_aql_in_production_code() -> None:
    """Production Python code should not mix reads and writes on one collection."""
    violations = _find_violations(_PRODUCTION_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))


@pytest.mark.unit
def test_no_mixed_read_write_aql_in_scripts() -> None:
    """Ensure no mixed read/write AQL patterns exist in scripts/."""
    if not _SCRIPTS_ROOT.exists():
        pytest.skip("scripts/ directory does not exist")

    violations = _find_violations(_SCRIPTS_ROOT)
    if violations:
        pytest.fail(_format_violations(violations))
