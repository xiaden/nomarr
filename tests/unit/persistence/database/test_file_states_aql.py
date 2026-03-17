"""Unit tests for FileStatesOperations (file_states_aql.py).

Verifies AQL queries are structured correctly for each state type.
Mock-based — runs without ArangoDB.
"""

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.file_states_aql import FileStatesOperations


@pytest.fixture
def mock_db():
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db):
    """Provide FileStatesOperations instance."""
    return FileStatesOperations(mock_db)


# ==================================================================
# ML Tagged state
# ==================================================================


class TestSetMlTagged:
    """Test set_ml_tagged() method."""

    @pytest.mark.unit
    def test_upsert_query_structure(self, ops, mock_db):
        """Executes UPSERT with correct bind vars."""
        ops.set_ml_tagged("library_files/abc", version="v1.0", tagged_at=1000)

        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]
        assert "UPSERT" in query
        assert "INSERT" in query
        assert "UPDATE" in query

        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["version"] == "v1.0"
        assert bind_vars["tagged_at"] == 1000
        assert bind_vars["state"] == "file_states/ml_tagged"
        assert bind_vars["@coll"] == "file_has_state"

    @pytest.mark.unit
    @patch("nomarr.persistence.database.file_states_aql.now_ms")
    def test_defaults_tagged_at_to_now(self, mock_now, ops, mock_db):
        """When tagged_at is None, uses now_ms()."""
        mock_now.return_value.value = 42000
        ops.set_ml_tagged("library_files/abc", version="v2.0")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tagged_at"] == 42000


class TestClearMlTagged:
    """Test clear_ml_tagged() method."""

    @pytest.mark.unit
    def test_remove_query(self, ops, mock_db):
        """Executes REMOVE query with correct filters."""
        ops.clear_ml_tagged("library_files/abc")

        query = mock_db.aql.execute.call_args[0][0]
        assert "REMOVE" in query
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["state"] == "file_states/ml_tagged"


class TestIsMlTagged:
    """Test is_ml_tagged() method."""

    @pytest.mark.unit
    def test_returns_true_when_edge_exists(self, ops, mock_db):
        """Returns True when cursor yields a result."""
        mock_db.aql.execute.return_value = iter([True])
        assert ops.is_ml_tagged("library_files/abc") is True

    @pytest.mark.unit
    def test_returns_false_when_no_edge(self, ops, mock_db):
        """Returns False when cursor is empty."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.is_ml_tagged("library_files/abc") is False


class TestGetMlTagged:
    """Test get_ml_tagged() method."""

    @pytest.mark.unit
    def test_returns_edge_attrs(self, ops, mock_db):
        """Returns edge attributes when edge exists."""
        mock_db.aql.execute.return_value = iter([{"version": "v1.0", "tagged_at": 1000}])
        result = ops.get_ml_tagged("library_files/abc")
        assert result == {"version": "v1.0", "tagged_at": 1000}

    @pytest.mark.unit
    def test_returns_none_when_no_edge(self, ops, mock_db):
        """Returns None when no edge exists."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.get_ml_tagged("library_files/abc") is None


class TestGetUntaggedFileIds:
    """Test get_untagged_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops, mock_db):
        """Returns list of untagged file IDs."""
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
        result = ops.get_untagged_file_ids(library_id="libraries/123", limit=10)
        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_query_filters_by_library(self, ops, mock_db):
        """When library_id is provided, query includes library filter."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids(library_id="libraries/123")
        query = mock_db.aql.execute.call_args[0][0]
        assert "library_id" in query

    @pytest.mark.unit
    def test_query_no_library_filter_when_none(self, ops, mock_db):
        """When library_id is None, no library filter in query."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids(library_id=None)
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "library_id" not in bind_vars

    @pytest.mark.unit
    def test_uses_left_anti_join_pattern(self, ops, mock_db):
        """Query uses subquery for LEFT ANTI JOIN (files without edge)."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids()
        query = mock_db.aql.execute.call_args[0][0]
        assert "has_state == 0" in query


class TestLibraryHasTaggedFiles:
    """Test library_has_tagged_files() method."""

    @pytest.mark.unit
    def test_returns_true(self, ops, mock_db):
        """Returns True when cursor yields a result."""
        mock_db.aql.execute.return_value = iter([True])
        assert ops.library_has_tagged_files("libraries/1") is True

    @pytest.mark.unit
    def test_returns_false(self, ops, mock_db):
        """Returns False when cursor is empty."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.library_has_tagged_files("libraries/1") is False


# ==================================================================
# Calibration state
# ==================================================================


class TestSetCalibrated:
    """Test set_calibrated() method."""

    @pytest.mark.unit
    def test_upsert_query_structure(self, ops, mock_db):
        """Executes UPSERT with correct bind vars."""
        ops.set_calibrated("library_files/abc", calibration_hash="md5hash", calibrated_at=2000)

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["hash"] == "md5hash"
        assert bind_vars["calibrated_at"] == 2000
        assert bind_vars["state"] == "file_states/calibrated"


class TestSetCalibratedBatch:
    """Test set_calibrated_batch() method."""

    @pytest.mark.unit
    def test_batch_upsert(self, ops, mock_db):
        """Creates docs list and runs batch UPSERT."""
        items = [("library_files/a", "hash1"), ("library_files/b", "hash2")]
        ops.set_calibrated_batch(items)

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        docs = bind_vars["docs"]
        assert len(docs) == 2
        assert docs[0]["_from"] == "library_files/a"
        assert docs[0]["hash"] == "hash1"
        assert docs[1]["_from"] == "library_files/b"

    @pytest.mark.unit
    def test_empty_batch_noop(self, ops, mock_db):
        """Empty batch does not execute AQL."""
        ops.set_calibrated_batch([])
        mock_db.aql.execute.assert_not_called()


class TestClearAllCalibrated:
    """Test clear_all_calibrated() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of removed edges."""
        mock_db.aql.execute.return_value = iter([42])
        assert ops.clear_all_calibrated() == 42

    @pytest.mark.unit
    def test_remove_query_filters_by_state(self, ops, mock_db):
        """Query removes only calibrated edges."""
        mock_db.aql.execute.return_value = iter([0])
        ops.clear_all_calibrated()
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["state"] == "file_states/calibrated"


class TestGetCalibrationStatusByLibrary:
    """Test get_calibration_status_by_library() method."""

    @pytest.mark.unit
    def test_returns_status_list(self, ops, mock_db):
        """Returns list of per-library status dicts."""
        expected = [{"library_id": "lib1", "total_files": 10, "current_count": 8, "outdated_count": 2}]
        mock_db.aql.execute.return_value = iter(expected)
        result = ops.get_calibration_status_by_library("expected_hash")
        assert result == expected


# ==================================================================
# Reconciliation state
# ==================================================================


class TestSetReconciled:
    """Test set_reconciled() method."""

    @pytest.mark.unit
    def test_upsert_query_structure(self, ops, mock_db):
        """Executes UPSERT with all reconciliation attrs."""
        ops.set_reconciled(
            "library_files/abc",
            mode="full",
            calibration_hash="hash1",
            written_at=3000,
            has_namespace=True,
        )

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["mode"] == "full"
        assert bind_vars["calibration_hash"] == "hash1"
        assert bind_vars["written_at"] == 3000
        assert bind_vars["has_namespace"] is True
        assert bind_vars["state"] == "file_states/reconciled"


class TestGetFilesNeedingReconciliation:
    """Test get_files_needing_reconciliation() method."""

    @pytest.mark.unit
    def test_returns_file_list(self, ops, mock_db):
        """Returns list of file dicts."""
        expected = [{"_id": "library_files/1", "_key": "1", "path": "/music/song.mp3"}]
        mock_db.aql.execute.return_value = iter(expected)
        result = ops.get_files_needing_reconciliation("lib1", "full", "hash1")
        assert result == expected

    @pytest.mark.unit
    def test_includes_hash_clause_when_provided(self, ops, mock_db):
        """Dynamic hash clause included when calibration_hash is not None."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_files_needing_reconciliation("lib1", "full", "hash1")
        query = mock_db.aql.execute.call_args[0][0]
        assert "calibration_hash" in query

    @pytest.mark.unit
    def test_excludes_hash_clause_when_none(self, ops, mock_db):
        """No hash comparison when calibration_hash is None."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_files_needing_reconciliation("lib1", "full", None)
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "calibration_hash" not in bind_vars


class TestCountFilesNeedingReconciliation:
    """Test count_files_needing_reconciliation() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns integer count."""
        mock_db.aql.execute.return_value = iter([15])
        assert ops.count_files_needing_reconciliation("lib1", "full", "hash1") == 15

    @pytest.mark.unit
    def test_returns_zero_when_empty(self, ops, mock_db):
        """Returns 0 when cursor is empty."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.count_files_needing_reconciliation("lib1", "full", None) == 0


# ==================================================================
# Cross-state utilities
# ==================================================================


class TestClearAllStates:
    """Test clear_all_states() method."""

    @pytest.mark.unit
    def test_returns_removed_count(self, ops, mock_db):
        """Returns number of edges removed."""
        mock_db.aql.execute.return_value = iter([3])
        assert ops.clear_all_states("library_files/abc") == 3

    @pytest.mark.unit
    def test_filters_by_file_id_only(self, ops, mock_db):
        """Query filters on _from only (removes all state types)."""
        mock_db.aql.execute.return_value = iter([0])
        ops.clear_all_states("library_files/abc")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "_from" in query
        assert bind_vars["file_id"] == "library_files/abc"
        assert "state" not in bind_vars  # No specific state filter
