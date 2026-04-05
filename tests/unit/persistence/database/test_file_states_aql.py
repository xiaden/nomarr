"""Unit tests for FileStatesOperations (file_states_aql.py).

Verifies AQL queries are structured correctly for each state type.
Mock-based — runs without ArangoDB.
"""

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.file_states_aql import (
    FileStatesOperations,
)


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
# State transition (set_tagged / set_not_tagged etc.)
# ==================================================================


class TestSetTagged:
    """Test set_tagged() method."""

    @pytest.mark.unit
    def test_calls_transition_state(self, ops, mock_db):
        """Executes AQL with correct bind vars for tagged transition."""
        ops.set_tagged("library_files/abc")

        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]
        bind_vars = call_args[1]["bind_vars"]

        # Verify transition query structure
        assert "REMOVE" in query or "INSERT" in query
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["new_state"] == "file_states/tagged"


class TestSetNotTagged:
    """Test set_not_tagged() method."""

    @pytest.mark.unit
    def test_calls_transition_state(self, ops, mock_db):
        """Executes AQL with correct bind vars for not_tagged transition."""
        ops.set_not_tagged("library_files/abc")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["new_state"] == "file_states/not_tagged"


# ==================================================================
# Untagged file queries
# ==================================================================


class TestGetUntaggedFileIds:
    """Test get_untagged_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops, mock_db):
        """Returns list of untagged file IDs."""
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
        result = ops.get_untagged_file_ids(library_id="libraries/123", limit=10)
        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_query_scopes_to_library_when_provided(self, ops, mock_db):
        """When library_id is provided, query uses edge traversal via library_contains_file."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids(library_id="libraries/123")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"

    @pytest.mark.unit
    def test_query_uses_inbound_traversal_when_no_library(self, ops, mock_db):
        """When library_id is None, query uses INBOUND traversal from not_tagged vertex."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids(library_id=None)
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "INBOUND @not_tagged file_has_state" in query
        assert "library_id" not in bind_vars

    @pytest.mark.unit
    def test_uses_inbound_not_tagged_pattern(self, ops, mock_db):
        """Query uses INBOUND traversal from not_tagged state vertex."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_untagged_file_ids()
        query = mock_db.aql.execute.call_args[0][0]
        assert "INBOUND @not_tagged file_has_state" in query


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

    @pytest.mark.unit
    def test_query_uses_edge_traversal(self, ops, mock_db):
        """Query uses edge traversal via library_contains_file."""
        mock_db.aql.execute.return_value = iter([])
        ops.library_has_tagged_files("libraries/123")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"


# ==================================================================
# Calibration state
# ==================================================================


class TestSetCalibrated:
    """Test set_calibrated() method."""

    @pytest.mark.unit
    def test_transition_query_structure(self, ops, mock_db):
        """Executes transition AQL with correct bind vars."""
        ops.set_calibrated("library_files/abc")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"
        assert bind_vars["new_state"] == "file_states/calibrated"


class TestBulkSetNotCalibrated:
    """Test bulk_set_not_calibrated() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.return_value = iter([1, 1, 1])
        assert ops.bulk_set_not_calibrated() == 3

    @pytest.mark.unit
    def test_query_filters_by_calibrated_state(self, ops, mock_db):
        """Query transitions calibrated edges to not_calibrated."""
        mock_db.aql.execute.return_value = iter([])
        ops.bulk_set_not_calibrated()
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["calibrated"] == "file_states/calibrated"
        assert bind_vars["not_calibrated"] == "file_states/not_calibrated"


class TestBulkSetScanned:
    """Test bulk_set_scanned() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.return_value = iter([1, 1])
        assert ops.bulk_set_scanned(["library_files/a", "library_files/b"]) == 2

    @pytest.mark.unit
    def test_query_filters_by_not_scanned_and_file_ids(self, ops, mock_db):
        """Query transitions not_scanned edges to scanned for specified file IDs only."""
        mock_db.aql.execute.return_value = iter([])
        file_ids = ["library_files/a", "library_files/b"]
        ops.bulk_set_scanned(file_ids)
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert bind_vars["not_scanned"] == "file_states/not_scanned"
        assert bind_vars["scanned"] == "file_states/scanned"
        assert bind_vars["file_ids"] == file_ids
        assert "e._from IN @file_ids" in query

    @pytest.mark.unit
    def test_empty_file_ids_returns_zero(self, ops, mock_db):
        """Returns 0 when no file IDs are provided."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.bulk_set_scanned([]) == 0


class TestBulkSetNotVectorsExtracted:
    """Test bulk_set_not_vectors_extracted() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.return_value = iter([1, 1, 1])
        assert ops.bulk_set_not_vectors_extracted() == 3

    @pytest.mark.unit
    def test_query_filters_by_vectors_extracted_state(self, ops, mock_db):
        """Query transitions vectors_extracted edges to not_vectors_extracted."""
        mock_db.aql.execute.return_value = iter([])
        ops.bulk_set_not_vectors_extracted()
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["vectors_extracted"] == "file_states/vectors_extracted"
        assert bind_vars["not_vectors_extracted"] == "file_states/not_vectors_extracted"


class TestBulkSetNotErrored:
    """Test bulk_set_not_errored() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.return_value = iter([1, 1])
        assert ops.bulk_set_not_errored(["library_files/a", "library_files/b"]) == 2

    @pytest.mark.unit
    def test_query_filters_by_errored_and_file_ids(self, ops, mock_db):
        """Query transitions errored edges to not_errored for specified file IDs only."""
        mock_db.aql.execute.return_value = iter([])
        file_ids = ["library_files/a", "library_files/b"]
        ops.bulk_set_not_errored(file_ids)
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert bind_vars["errored"] == "file_states/errored"
        assert bind_vars["not_errored"] == "file_states/not_errored"
        assert bind_vars["file_ids"] == file_ids
        assert "e._from IN @file_ids" in query

    @pytest.mark.unit
    def test_empty_file_ids_returns_zero(self, ops, mock_db):
        """Returns 0 when no file IDs are provided."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.bulk_set_not_errored([]) == 0


class TestDiscoverNextUntaggedFileErroredExclusion:
    """Test discover_next_untagged_file() excludes errored files."""

    @pytest.mark.unit
    def test_query_excludes_errored_ids(self, ops, mock_db):
        """Query builds errored_ids LET and filters them out."""
        mock_db.aql.execute.return_value = iter([])
        ops.discover_next_untagged_file()
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "INBOUND @errored file_has_state" in query
        assert "NOT IN errored_ids" in query
        assert bind_vars["errored"] == "file_states/errored"

    @pytest.mark.unit
    def test_query_still_excludes_too_short(self, ops, mock_db):
        """Query still excludes too_short files alongside errored."""
        mock_db.aql.execute.return_value = iter([])
        ops.discover_next_untagged_file()
        query = mock_db.aql.execute.call_args[0][0]

        assert "NOT IN too_short_ids" in query
        assert "NOT IN errored_ids" in query


class TestGetCalibrationStatusByLibrary:
    """Test get_calibration_status_by_library() method."""

    @pytest.mark.unit
    def test_returns_status_list(self, ops, mock_db):
        """Returns list of per-library status dicts with expected structure."""
        expected = [{"library_id": "libraries/1", "calibrated_count": 8, "not_calibrated_count": 2}]
        mock_db.aql.execute.return_value = iter(expected)
        result = ops.get_calibration_status_by_library()
        assert result == expected

    @pytest.mark.unit
    def test_query_uses_edge_traversal_for_aggregation(self, ops, mock_db):
        """Query aggregates files via edge traversal from libraries."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_calibration_status_by_library()
        query = mock_db.aql.execute.call_args[0][0]

        assert "FOR lib IN libraries" in query
        assert "OUTBOUND lib" in query


# ==================================================================
# Stale file queries (replacement for reconciliation)
# ==================================================================


class TestGetStaleFileIds:
    """Test get_stale_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops, mock_db):
        """Returns list of stale file IDs."""
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
        result = ops.get_stale_file_ids(library_id="libraries/1")
        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_scopes_to_library_when_provided(self, ops, mock_db):
        """When library_id is provided, query uses edge traversal."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_stale_file_ids(library_id="libraries/123")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"

    @pytest.mark.unit
    def test_uses_inbound_tags_stale(self, ops, mock_db):
        """Query traverses INBOUND from tags_stale vertex."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_stale_file_ids()
        query = mock_db.aql.execute.call_args[0][0]
        assert "INBOUND @tags_stale file_has_state" in query


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


# ==================================================================
# Errored file queries
# ==================================================================


class TestGetErroredFileIds:
    """Test get_errored_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops, mock_db):
        """Returns list of errored file IDs."""
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
        result = ops.get_errored_file_ids(library_id="abc123", limit=10)
        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_query_scopes_to_library(self, ops, mock_db):
        """Query uses edge traversal via library_contains_file scoped to library."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_errored_file_ids(library_id="abc123")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/abc123"

    @pytest.mark.unit
    def test_query_filters_by_errored_state(self, ops, mock_db):
        """Query filters edges by errored state vertex."""
        mock_db.aql.execute.return_value = iter([])
        ops.get_errored_file_ids(library_id="abc123")
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "e._to == @errored" in query
        assert bind_vars["errored"] == "file_states/errored"


class TestCountErroredFiles:
    """Test count_errored_files() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns integer count from cursor."""
        mock_db.aql.execute.return_value = iter([5])
        result = ops.count_errored_files(library_id="abc123")
        assert result == 5

    @pytest.mark.unit
    def test_returns_zero_when_empty_cursor(self, ops, mock_db):
        """Returns 0 when cursor yields no results."""
        mock_db.aql.execute.return_value = iter([])
        result = ops.count_errored_files(library_id="abc123")
        assert result == 0

    @pytest.mark.unit
    def test_query_scopes_to_library(self, ops, mock_db):
        """Query bind_vars includes library_id prefixed with 'libraries/'."""
        mock_db.aql.execute.return_value = iter([0])
        ops.count_errored_files(library_id="abc123")
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert bind_vars["library_id"] == "libraries/abc123"
