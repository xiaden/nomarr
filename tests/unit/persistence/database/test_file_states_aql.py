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
        """Delegates tagged transitions through the shared axis helper."""
        ops._transition_state = MagicMock()  # type: ignore[method-assign]
        ops.set_tagged("library_files/abc")

        ops._transition_state.assert_called_once_with("library_files/abc", "tagged", to_positive=True)


class TestSetNotTagged:
    """Test set_not_tagged() method."""

    @pytest.mark.unit
    def test_calls_transition_state(self, ops, mock_db):
        """Delegates not_tagged transitions through the shared axis helper."""
        ops._transition_state = MagicMock()  # type: ignore[method-assign]
        ops.set_not_tagged("library_files/abc")

        ops._transition_state.assert_called_once_with("library_files/abc", "tagged", to_positive=False)


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


class TestGetFilesWithIncompleteTags:
    """Tests for get_files_with_incomplete_tags()."""

    @pytest.mark.unit
    def test_returns_rows_from_cursor(self, ops, mock_db):
        """Returns the cursor rows unchanged."""
        expected = [
            {
                "file_id": "library_files/1",
                "file_key": "1",
                "library_id": "libraries/123",
                "matched_count": 1,
                "missing_count": 0,
                "missing_heads": [],
            }
        ]
        mock_db.aql.execute.return_value = iter(expected)

        result = ops.get_files_with_incomplete_tags(
            expected_heads=[{"head_key": "mood", "labels": ["happy"], "model_key_for_tag": "model"}],
            namespace_prefix="nom:",
            library_id="libraries/123",
        )

        assert result == expected

    @pytest.mark.unit
    def test_library_scoped_query_uses_edge_filter_and_bind_var_library_id(self, ops, mock_db):
        """Library scoping should use library_contains_file traversal and return @library_id."""
        mock_db.aql.execute.return_value = iter([])

        ops.get_files_with_incomplete_tags(
            expected_heads=[{"head_key": "mood", "labels": ["happy"], "model_key_for_tag": "model"}],
            namespace_prefix="nom:",
            library_id="libraries/123",
        )

        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "FOR lib IN INBOUND file._id library_contains_file" in query
        assert "FILTER lib._id == @library_id" in query
        assert "library_id: @library_id" in query
        assert "FILTER file.library_id == @library_id" not in query
        assert bind_vars["library_id"] == "libraries/123"


# ==================================================================
# Calibration state
# ==================================================================


class TestSetCalibrated:
    """Test set_calibrated() method."""

    @pytest.mark.unit
    def test_transition_query_structure(self, ops, mock_db):
        """Delegates calibrated transitions through the shared axis helper."""
        ops._transition_state = MagicMock()  # type: ignore[method-assign]
        ops.set_calibrated("library_files/abc")

        ops._transition_state.assert_called_once_with("library_files/abc", "calibrated", to_positive=True)


class TestBulkSetNotCalibrated:
    """Test bulk_set_not_calibrated() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.side_effect = [
            iter(
                [
                    {"key": "k1", "from_id": "library_files/1"},
                    {"key": "k2", "from_id": "library_files/2"},
                    {"key": "k3", "from_id": "library_files/3"},
                ]
            ),
            MagicMock(),
            MagicMock(),
        ]
        assert ops.bulk_set_not_calibrated() == 3

    @pytest.mark.unit
    def test_query_filters_by_calibrated_state(self, ops, mock_db):
        """Query transitions calibrated edges to not_calibrated."""
        mock_db.aql.execute.return_value = iter([])
        ops.bulk_set_not_calibrated()
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert read_bind_vars["calibrated"] == "file_states/calibrated"

        mock_db.reset_mock()
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/1"}]),
            MagicMock(),
            MagicMock(),
        ]
        ops.bulk_set_not_calibrated()
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert insert_bind_vars["not_calibrated"] == "file_states/not_calibrated"


class TestBulkSetScanned:
    """Test bulk_set_scanned() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.side_effect = [
            iter(
                [
                    {"key": "k1", "from_id": "library_files/a"},
                    {"key": "k2", "from_id": "library_files/b"},
                ]
            ),
            MagicMock(),
            MagicMock(),
        ]
        assert ops.bulk_set_scanned(["library_files/a", "library_files/b"]) == 2

    @pytest.mark.unit
    def test_query_filters_by_not_scanned_and_file_ids(self, ops, mock_db):
        """Query transitions not_scanned edges to scanned for specified file IDs only."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/a"}]),
            MagicMock(),
            MagicMock(),
        ]
        file_ids = ["library_files/a", "library_files/b"]
        ops.bulk_set_scanned(file_ids)
        read_query = mock_db.aql.execute.call_args_list[0][0][0]
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]

        assert read_bind_vars["not_scanned"] == "file_states/not_scanned"
        assert read_bind_vars["file_ids"] == file_ids
        assert insert_bind_vars["scanned"] == "file_states/scanned"
        assert "e._from IN @file_ids" in read_query

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
        mock_db.aql.execute.side_effect = [
            iter(
                [
                    {"key": "k1", "from_id": "library_files/1"},
                    {"key": "k2", "from_id": "library_files/2"},
                    {"key": "k3", "from_id": "library_files/3"},
                ]
            ),
            MagicMock(),
            MagicMock(),
        ]
        assert ops.bulk_set_not_vectors_extracted() == 3

    @pytest.mark.unit
    def test_query_filters_by_vectors_extracted_state(self, ops, mock_db):
        """Query transitions vectors_extracted edges to not_vectors_extracted."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/1"}]),
            MagicMock(),
            MagicMock(),
        ]
        ops.bulk_set_not_vectors_extracted()
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert read_bind_vars["vectors_extracted"] == "file_states/vectors_extracted"
        assert insert_bind_vars["not_vectors_extracted"] == "file_states/not_vectors_extracted"


class TestBulkSetNotErrored:
    """Test bulk_set_not_errored() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops, mock_db):
        """Returns number of transitioned edges."""
        mock_db.aql.execute.side_effect = [
            iter(
                [
                    {"key": "k1", "from_id": "library_files/a"},
                    {"key": "k2", "from_id": "library_files/b"},
                ]
            ),
            MagicMock(),
            MagicMock(),
        ]
        assert ops.bulk_set_not_errored(["library_files/a", "library_files/b"]) == 2

    @pytest.mark.unit
    def test_query_filters_by_errored_and_file_ids(self, ops, mock_db):
        """Query transitions errored edges to not_errored for specified file IDs only."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/a"}]),
            MagicMock(),
            MagicMock(),
        ]
        file_ids = ["library_files/a", "library_files/b"]
        ops.bulk_set_not_errored(file_ids)
        read_query = mock_db.aql.execute.call_args_list[0][0][0]
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]

        assert read_bind_vars["errored"] == "file_states/errored"
        assert read_bind_vars["file_ids"] == file_ids
        assert insert_bind_vars["not_errored"] == "file_states/not_errored"
        assert "e._from IN @file_ids" in read_query

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


# ==================================================================
# _transition_state internals
# ==================================================================


class TestTransitionState:
    """Test _transition_state() bind variables and query contract."""

    @pytest.mark.unit
    def test_positive_transition_passes_correct_new_state(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Positive transition binds the positive state vertex as new_state."""
        mock_db.aql.execute.return_value = MagicMock()

        ops._transition_state("library_files/abc", "tagged", to_positive=True)

        assert mock_db.aql.execute.call_count == 1
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["new_state"] == "file_states/tagged"

    @pytest.mark.unit
    def test_negative_transition_passes_correct_new_state(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Negative transition binds the negative state vertex as new_state."""
        mock_db.aql.execute.return_value = MagicMock()

        ops._transition_state("library_files/abc", "tagged", to_positive=False)

        assert mock_db.aql.execute.call_count == 1
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["new_state"] == "file_states/not_tagged"

    @pytest.mark.unit
    def test_query_bind_vars_include_both_axis_vertices(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Bind vars include both positive and negative state vertices for the axis so old edges can be removed."""
        mock_db.aql.execute.return_value = MagicMock()

        ops._transition_state("library_files/abc", "tagged", to_positive=True)

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["positive"] == "file_states/tagged"
        assert bind_vars["negative"] == "file_states/not_tagged"
        assert bind_vars["file_id"] == "library_files/abc"


# ==================================================================
# bulk_set_tags_stale
# ==================================================================


class TestBulkSetTagsStale:
    """Test bulk_set_tags_stale() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns number of transitioned edges."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/1"}, {"key": "k2", "from_id": "library_files/2"}]),
            MagicMock(),
            MagicMock(),
        ]
        assert ops.bulk_set_tags_stale() == 2

    @pytest.mark.unit
    def test_empty_result_returns_zero(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns 0 when no edges match without further AQL calls."""
        mock_db.aql.execute.return_value = iter([])
        assert ops.bulk_set_tags_stale() == 0
        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_read_query_filters_by_tags_current(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Read bind_vars reference the tags_current state vertex."""
        mock_db.aql.execute.return_value = iter([])
        ops.bulk_set_tags_stale()
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert read_bind_vars["tags_current"] == "file_states/tags_current"

    @pytest.mark.unit
    def test_insert_uses_tags_stale_state(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Insert phase bind_vars reference the tags_stale state vertex."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/1"}]),
            MagicMock(),
            MagicMock(),
        ]
        ops.bulk_set_tags_stale()
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert insert_bind_vars["tags_stale"] == "file_states/tags_stale"

    @pytest.mark.unit
    def test_library_scoped_query_uses_outbound_traversal(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """When library_id provided, read query scopes via OUTBOUND library traversal."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "k1", "from_id": "library_files/1"}]),
            MagicMock(),
            MagicMock(),
        ]
        ops.bulk_set_tags_stale(library_id="libraries/1")
        read_query = mock_db.aql.execute.call_args_list[0][0][0]
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert "OUTBOUND @library_id library_contains_file" in read_query
        assert read_bind_vars["library_id"] == "libraries/1"

    @pytest.mark.unit
    def test_global_query_does_not_include_library_id_bind_var(
        self, ops: FileStatesOperations, mock_db: MagicMock
    ) -> None:
        """When called without library_id, read bind_vars do not include library_id."""
        mock_db.aql.execute.return_value = iter([])
        ops.bulk_set_tags_stale()
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert "library_id" not in read_bind_vars


# ==================================================================
# clear_tagged_batch
# ==================================================================


class TestClearTaggedBatch:
    """Test clear_tagged_batch() method."""

    @pytest.mark.unit
    def test_returns_file_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns number of file IDs processed."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock()]
        assert ops.clear_tagged_batch(["library_files/1", "library_files/2"]) == 2

    @pytest.mark.unit
    def test_empty_list_returns_zero(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns 0 and issues no AQL calls when file_ids is empty."""
        assert ops.clear_tagged_batch([]) == 0
        assert mock_db.aql.execute.call_count == 0

    @pytest.mark.unit
    def test_two_phase_call_structure(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Issues exactly 2 AQL calls: remove then insert."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock()]
        ops.clear_tagged_batch(["library_files/1"])
        assert mock_db.aql.execute.call_count == 2

    @pytest.mark.unit
    def test_remove_query_filters_by_tagged_state(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Remove bind_vars reference tagged state and the provided file_ids."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock()]
        ops.clear_tagged_batch(["library_files/1"])
        remove_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert remove_bind_vars["tagged"] == "file_states/tagged"
        assert remove_bind_vars["file_ids"] == ["library_files/1"]

    @pytest.mark.unit
    def test_insert_query_uses_not_tagged_state(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Insert bind_vars reference the not_tagged state vertex."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock()]
        ops.clear_tagged_batch(["library_files/1"])
        insert_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert insert_bind_vars["not_tagged"] == "file_states/not_tagged"


# ==================================================================
# Initialization operations
# ==================================================================


class TestInitializeFileStates:
    """Test initialize_file_states() method."""

    @pytest.mark.unit
    def test_calls_aql_execute_once(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Calls AQL execute exactly once for one file."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states("library_files/abc")

        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_bind_vars_include_file_id(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes the provided file_id in bind_vars."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states("library_files/abc")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_id"] == "library_files/abc"

    @pytest.mark.unit
    def test_bind_vars_include_negative_states(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes a non-empty negative_states list in bind_vars."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states("library_files/abc")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert isinstance(bind_vars["negative_states"], list)
        assert bind_vars["negative_states"]

    @pytest.mark.unit
    def test_bind_vars_include_edge_collection(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes the file_has_state edge collection in bind_vars."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states("library_files/abc")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["@coll"] == "file_has_state"


class TestInitializeFileStatesBatch:
    """Test initialize_file_states_batch() method."""

    @pytest.mark.unit
    def test_calls_aql_execute_once(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Calls AQL execute exactly once for a non-empty batch."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states_batch(["library_files/1", "library_files/2"])

        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_empty_list_skips_execute(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Skips AQL execution when file_ids is empty."""
        ops.initialize_file_states_batch([])

        assert mock_db.aql.execute.call_count == 0

    @pytest.mark.unit
    def test_bind_vars_include_file_ids(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes the full file_ids list in bind_vars."""
        mock_db.aql.execute.return_value = MagicMock()
        file_ids = ["library_files/1", "library_files/2", "library_files/3"]

        ops.initialize_file_states_batch(file_ids)

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["file_ids"] == file_ids

    @pytest.mark.unit
    def test_bind_vars_include_negative_states(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes a non-empty negative_states list in bind_vars."""
        mock_db.aql.execute.return_value = MagicMock()

        ops.initialize_file_states_batch(["library_files/1"])

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert isinstance(bind_vars["negative_states"], list)
        assert bind_vars["negative_states"]


# ==================================================================
# Batch reset and pending tag write queries
# ==================================================================


class TestClearAllStatesBatch:
    """Test clear_all_states_batch() method."""

    @pytest.mark.unit
    def test_returns_removed_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns the removed edge count from the cursor."""
        mock_db.aql.execute.return_value = iter([5])

        result = ops.clear_all_states_batch(["library_files/1", "library_files/2"])

        assert result == 5

    @pytest.mark.unit
    def test_empty_list_returns_zero(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns zero and skips AQL when file_ids is empty."""
        result = ops.clear_all_states_batch([])

        assert result == 0
        assert mock_db.aql.execute.call_count == 0

    @pytest.mark.unit
    def test_query_filters_by_file_ids(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Uses the provided file_ids list and filters on _from IN @file_ids."""
        file_ids = ["library_files/1", "library_files/2"]
        mock_db.aql.execute.return_value = iter([0])

        ops.clear_all_states_batch(file_ids)

        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "_from IN @file_ids" in query
        assert bind_vars["file_ids"] == file_ids

    @pytest.mark.unit
    def test_returns_zero_when_cursor_empty(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns zero when the cursor yields no count."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.clear_all_states_batch(["library_files/1"])

        assert result == 0


class TestCountPendingTagWrites:
    """Test count_pending_tag_writes() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns the count produced by the cursor."""
        mock_db.aql.execute.return_value = iter([4])

        result = ops.count_pending_tag_writes()

        assert result == 4

    @pytest.mark.unit
    def test_returns_zero_for_empty_cursor(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns zero when the cursor is empty."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.count_pending_tag_writes()

        assert result == 0

    @pytest.mark.unit
    def test_query_uses_tags_not_written_bind_var(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Binds the tags_not_written state vertex in the query."""
        mock_db.aql.execute.return_value = iter([0])

        ops.count_pending_tag_writes()

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tags_not_written"] == "file_states/tags_not_written"


class TestGetPendingTagWriteFileIds:
    """Test get_pending_tag_write_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns file IDs from the cursor in order."""
        expected = ["library_files/1", "library_files/2"]
        mock_db.aql.execute.return_value = iter(expected)

        result = ops.get_pending_tag_write_file_ids()

        assert result == expected

    @pytest.mark.unit
    def test_query_uses_tags_not_written_bind_var(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Binds the tags_not_written state vertex in the query."""
        mock_db.aql.execute.return_value = iter([])

        ops.get_pending_tag_write_file_ids()

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tags_not_written"] == "file_states/tags_not_written"

    @pytest.mark.unit
    def test_custom_limit_is_passed_as_bind_var(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Passes a custom limit through bind_vars."""
        mock_db.aql.execute.return_value = iter([])

        ops.get_pending_tag_write_file_ids(limit=50)

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["limit"] == 50


# ==================================================================
# Aggregate and lookup queries
# ==================================================================


class TestCountUntaggedFiles:
    """Test count_untagged_files() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns the count produced by the scalar query."""
        mock_db.aql.execute.return_value = iter([7])

        result = ops.count_untagged_files()

        assert result == 7

    @pytest.mark.unit
    def test_returns_zero_when_empty(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns zero when the scalar query yields zero."""
        mock_db.aql.execute.return_value = iter([0])

        result = ops.count_untagged_files()

        assert result == 0

    @pytest.mark.unit
    def test_query_includes_not_tagged_bind_var(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Binds the not_tagged state vertex in the query."""
        mock_db.aql.execute.return_value = iter([0])

        ops.count_untagged_files()

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["not_tagged"] == "file_states/not_tagged"

    @pytest.mark.unit
    def test_library_scoped_query_uses_outbound_traversal(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Library-scoped count uses OUTBOUND traversal via library_contains_file."""
        mock_db.aql.execute.return_value = iter([0])

        ops.count_untagged_files(library_id="libraries/123")

        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"


class TestCountUncalibratedFiles:
    """Test count_uncalibrated_files() method."""

    @pytest.mark.unit
    def test_returns_count(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns the count produced by the scalar query."""
        mock_db.aql.execute.return_value = iter([3])

        result = ops.count_uncalibrated_files()

        assert result == 3

    @pytest.mark.unit
    def test_query_uses_not_calibrated_bind_var(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Binds the not_calibrated state vertex in the query."""
        mock_db.aql.execute.return_value = iter([0])

        ops.count_uncalibrated_files()

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["not_calibrated"] == "file_states/not_calibrated"


class TestGetUncalibratedTaggedFileIds:
    """Test get_uncalibrated_tagged_file_ids() method."""

    @pytest.mark.unit
    def test_returns_file_ids(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns matching file IDs from the cursor."""
        mock_db.aql.execute.return_value = iter(["library_files/1"])

        result = ops.get_uncalibrated_tagged_file_ids("libraries/123")

        assert result == ["library_files/1"]

    @pytest.mark.unit
    def test_query_uses_tagged_and_not_calibrated_bind_vars(
        self, ops: FileStatesOperations, mock_db: MagicMock
    ) -> None:
        """Binds the tagged and not_calibrated state vertices in the query."""
        mock_db.aql.execute.return_value = iter([])

        ops.get_uncalibrated_tagged_file_ids("libraries/123")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tagged"] == "file_states/tagged"
        assert bind_vars["not_calibrated"] == "file_states/not_calibrated"

    @pytest.mark.unit
    def test_query_uses_library_id(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Binds the provided library_id for scoping."""
        mock_db.aql.execute.return_value = iter([])

        ops.get_uncalibrated_tagged_file_ids("libraries/123")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["library_id"] == "libraries/123"


# ==================================================================
# discover_next_untagged_file additional coverage
# ==================================================================


class TestDiscoverNextUntaggedFile:
    """Test discover_next_untagged_file() general behavior."""

    @pytest.mark.unit
    def test_returns_none_when_no_file_found(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns None when the cursor is empty."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.discover_next_untagged_file()

        assert result is None

    @pytest.mark.unit
    def test_returns_file_document_when_found(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Returns the first file document when a match exists."""
        expected = {"_id": "library_files/1"}
        mock_db.aql.execute.return_value = iter([expected])

        result = ops.discover_next_untagged_file()

        assert result == expected

    @pytest.mark.unit
    def test_library_scoped_query_uses_outbound_traversal(self, ops: FileStatesOperations, mock_db: MagicMock) -> None:
        """Library-scoped discovery uses OUTBOUND traversal via library_contains_file."""
        mock_db.aql.execute.return_value = iter([])

        ops.discover_next_untagged_file(library_id="libraries/123")

        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert "OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"

    @pytest.mark.unit
    def test_exclude_claimed_false_omits_worker_claim_filter(
        self, ops: FileStatesOperations, mock_db: MagicMock
    ) -> None:
        """Omits the worker_claims filter when exclude_claimed is False."""
        mock_db.aql.execute.return_value = iter([])

        ops.discover_next_untagged_file(exclude_claimed=False)

        query = mock_db.aql.execute.call_args[0][0]
        assert "worker_claims" not in query


class TestFindShortFilesMissingTooShort:
    """Tests for find_short_files_missing_too_short()."""

    @pytest.mark.unit
    def test_returns_list_of_file_ids(self, ops, mock_db):
        """Returns short file IDs from the cursor."""
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])

        result = ops.find_short_files_missing_too_short("libraries/123", 30)

        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_returns_empty_list_when_none_found(self, ops, mock_db):
        """Returns an empty list when no short files need healing."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.find_short_files_missing_too_short("libraries/123", 30)

        assert result == []

    @pytest.mark.unit
    def test_query_uses_outbound_library_traversal(self, ops, mock_db):
        """Query scopes files via OUTBOUND library_contains_file traversal."""
        mock_db.aql.execute.return_value = iter([])

        ops.find_short_files_missing_too_short("libraries/123", 30)

        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "FOR file IN OUTBOUND @library_id library_contains_file" in query
        assert bind_vars["library_id"] == "libraries/123"
        assert bind_vars["min_duration_s"] == 30
