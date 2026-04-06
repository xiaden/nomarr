"""Unit tests for LibraryPipelineStatesOps (library_pipeline_states_aql.py).

Verifies AQL queries are structured correctly for library pipeline state operations.
Mock-based — runs without ArangoDB.
"""

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_pipeline_states_aql import LibraryPipelineStatesOps


@pytest.fixture
def ops(mock_db):
    """Provide LibraryPipelineStatesOps instance."""
    return LibraryPipelineStatesOps(mock_db)


class TestTransitionState:
    """Tests for transition_state()."""

    @pytest.mark.unit
    def test_executes_remove_insert_query_with_expected_bind_vars(self, ops, mock_db):
        """Transitions to a new state using separate read, remove, and insert calls."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "edge123", "to": "library_pipeline_states/idle"}]),
            MagicMock(),
            MagicMock(),
        ]

        ops.transition_state("libraries/abc", "library_pipeline_states/scanning")

        assert mock_db.aql.execute.call_count == 3

        lookup_query = mock_db.aql.execute.call_args_list[0][0][0]
        lookup_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        assert "e._from == @library_id" in lookup_query
        assert lookup_bind_vars["library_id"] == "libraries/abc"

        remove_query = mock_db.aql.execute.call_args_list[1][0][0]
        remove_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert "REMOVE @old_key IN library_has_pipeline_state" in remove_query
        assert remove_bind_vars["old_key"] == "edge123"

        insert_query = mock_db.aql.execute.call_args_list[2][0][0]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert "INSERT" in insert_query
        assert insert_bind_vars["library_id"] == "libraries/abc"
        assert insert_bind_vars["to_state"] == "library_pipeline_states/scanning"

    @pytest.mark.unit
    def test_returns_early_when_library_already_in_target_state(self, ops, mock_db):
        """Skips the transition query when the current state already matches."""
        mock_db.aql.execute.return_value = iter([{"key": "edge123", "to": "library_pipeline_states/scanning"}])

        ops.transition_state("libraries/abc", "library_pipeline_states/scanning")

        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_inserts_without_remove_when_no_existing_edge(self, ops, mock_db):
        """Inserts a fresh edge when the library has no current pipeline state."""
        mock_db.aql.execute.side_effect = [iter([]), MagicMock()]

        ops.transition_state("libraries/new", "library_pipeline_states/idle")

        assert mock_db.aql.execute.call_count == 2

        lookup_query = mock_db.aql.execute.call_args_list[0][0][0]
        lookup_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_query = mock_db.aql.execute.call_args_list[1][0][0]
        insert_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]

        assert "e._from == @library_id" in lookup_query
        assert lookup_bind_vars["library_id"] == "libraries/new"
        assert "INSERT" in insert_query
        assert insert_bind_vars["library_id"] == "libraries/new"
        assert insert_bind_vars["to_state"] == "library_pipeline_states/idle"


class TestGetState:
    """Tests for get_state()."""

    @pytest.mark.unit
    def test_returns_state_key(self, ops, mock_db):
        """Returns the pipeline state vertex key, not the full _id."""
        mock_db.aql.execute.return_value = iter(["idle"])

        result = ops.get_state("libraries/abc")

        assert result == "idle"

    @pytest.mark.unit
    def test_raises_value_error_when_state_edge_missing(self, ops, mock_db):
        """Raises when the library has no pipeline state edge."""
        mock_db.aql.execute.return_value = iter([])

        with pytest.raises(ValueError, match="No pipeline state edge found"):
            ops.get_state("libraries/abc")


class TestGetLibrariesInState:
    """Tests for get_libraries_in_state()."""

    @pytest.mark.unit
    def test_returns_empty_list_when_no_libraries_in_state(self, ops, mock_db):
        """Returns an empty list when no libraries currently match the state."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.get_libraries_in_state("library_pipeline_states/write_ready")

        assert result == []

    @pytest.mark.unit
    def test_returns_library_ids_via_inbound_traversal(self, ops, mock_db):
        """Returns library document IDs for the requested state."""
        mock_db.aql.execute.return_value = iter(["libraries/1", "libraries/2"])

        result = ops.get_libraries_in_state("library_pipeline_states/write_ready")

        assert result == ["libraries/1", "libraries/2"]
        query = mock_db.aql.execute.call_args[0][0]
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]

        assert "INBOUND @state library_has_pipeline_state" in query
        assert bind_vars["state"] == "library_pipeline_states/write_ready"


class TestBulkTransition:
    """Tests for bulk_transition()."""

    @pytest.mark.unit
    def test_returns_zero_when_no_libraries_in_from_state(self, ops, mock_db):
        """Returns zero without remove/insert calls when no edges match the source state."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.bulk_transition(
            "library_pipeline_states/awaiting_calibration",
            "library_pipeline_states/calibrating",
        )

        assert result == 0
        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_returns_transitioned_count(self, ops, mock_db):
        """Returns the number of transitioned library edges."""
        mock_db.aql.execute.side_effect = [
            iter(
                [
                    {"key": "edge1", "from_id": "libraries/1"},
                    {"key": "edge2", "from_id": "libraries/2"},
                    {"key": "edge3", "from_id": "libraries/3"},
                ]
            ),
            MagicMock(),
            MagicMock(),
        ]

        result = ops.bulk_transition(
            "library_pipeline_states/awaiting_calibration",
            "library_pipeline_states/calibrating",
        )

        assert result == 3

    @pytest.mark.unit
    def test_filters_by_from_state_and_inserts_to_target_state(self, ops, mock_db):
        """Query scopes transitions by from_state and writes the new to_state."""
        mock_db.aql.execute.side_effect = [
            iter([{"key": "edge1", "from_id": "libraries/1"}]),
            MagicMock(),
            MagicMock(),
        ]

        ops.bulk_transition(
            "library_pipeline_states/awaiting_calibration",
            "library_pipeline_states/calibrating",
        )

        read_query = mock_db.aql.execute.call_args_list[0][0][0]
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]

        assert "e._to == @from_state" in read_query
        assert read_bind_vars["from_state"] == "library_pipeline_states/awaiting_calibration"
        assert insert_bind_vars["to_state"] == "library_pipeline_states/calibrating"


class TestFindMlCompleteLibraries:
    """Tests for find_ml_complete_libraries()."""

    @pytest.mark.unit
    def test_returns_empty_list_when_no_ml_running_libraries_match(self, ops, mock_db):
        """Returns an empty list when no completed ml_running libraries exist."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.find_ml_complete_libraries(min_files=100)

        assert result == []

    @pytest.mark.unit
    def test_returns_all_completed_libraries_above_threshold(self, ops, mock_db):
        """Completed libraries are returned even when tagged counts exceed the threshold."""
        rows = [
            {"library_id": "libraries/1", "tagged_count": 150},
            {"library_id": "libraries/2", "tagged_count": 250},
        ]
        mock_db.aql.execute.return_value = iter(rows)

        result = ops.find_ml_complete_libraries(min_files=100)

        assert result == rows

    @pytest.mark.unit
    def test_returns_all_completed_libraries_below_threshold(self, ops, mock_db):
        """The method does not apply caller-owned threshold filtering."""
        rows = [
            {"library_id": "libraries/low-1", "tagged_count": 12},
            {"library_id": "libraries/low-2", "tagged_count": 42},
        ]
        mock_db.aql.execute.return_value = iter(rows)

        result = ops.find_ml_complete_libraries(min_files=100)

        assert result == rows

    @pytest.mark.unit
    def test_returns_only_completed_rows_in_mixed_library_scenarios(self, ops, mock_db):
        """AQL result rows only include libraries where untagged count reached zero."""
        rows = [
            {"library_id": "libraries/complete-1", "tagged_count": 80},
            {"library_id": "libraries/complete-2", "tagged_count": 180},
        ]
        mock_db.aql.execute.return_value = iter(rows)

        result = ops.find_ml_complete_libraries(min_files=100)

        assert result == rows

    @pytest.mark.unit
    def test_query_filters_out_libraries_with_untagged_files(self, ops, mock_db):
        """The AQL includes the required ml_running and untagged==0 filters."""
        mock_db.aql.execute.return_value = iter(
            [
                {"library_id": "libraries/complete", "tagged_count": 101},
            ]
        )

        result = ops.find_ml_complete_libraries(min_files=500)

        assert result == [{"library_id": "libraries/complete", "tagged_count": 101}]

        query = mock_db.aql.execute.call_args[0][0]
        assert 'FILTER state_edge == "ml_running"' in query
        assert "FILTER untagged == 0" in query
        assert 'e._to == "file_states/not_tagged"' in query
        assert 'e._to == "file_states/tagged"' in query
        assert "RETURN { library_id: lib._id, tagged_count: tagged_count }" in query
