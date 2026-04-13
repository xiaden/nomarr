# ruff: noqa: N999
"""Unit tests for V023 library pipeline state derivation."""

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_DONE,
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_WRITE_READY,
)
from nomarr.migrations.V023_library_pipeline_states import _derive_pipeline_state, upgrade


class TestDerivePipelineState:
    """Tests for _derive_pipeline_state()."""

    @pytest.mark.unit
    def test_returns_idle_when_total_files_is_zero(self) -> None:
        """Returns idle when the library has no files."""
        result = _derive_pipeline_state(
            total_files=0,
            tagged_count=0,
            untagged_count=0,
            calibrated_count=0,
            written_count=0,
        )

        assert result == PIPELINE_IDLE

    @pytest.mark.unit
    def test_returns_idle_when_tagged_count_is_zero(self) -> None:
        """Returns idle when none of the files have been tagged yet."""
        result = _derive_pipeline_state(
            total_files=5,
            tagged_count=0,
            untagged_count=5,
            calibrated_count=0,
            written_count=0,
        )

        assert result == PIPELINE_IDLE

    @pytest.mark.unit
    def test_returns_ml_running_when_untagged_files_remain(self) -> None:
        """Returns ml_running while tagged coverage is incomplete."""
        result = _derive_pipeline_state(
            total_files=5,
            tagged_count=4,
            untagged_count=1,
            calibrated_count=4,
            written_count=4,
        )

        assert result == PIPELINE_ML_RUNNING

    @pytest.mark.unit
    def test_returns_too_small_when_tagged_count_below_internal_minimum(self) -> None:
        """Returns too_small when fully tagged libraries do not meet calibration minimum."""
        with patch(
            "nomarr.services.infrastructure.config_svc.INTERNAL_CALIBRATION_MIN_FILES",
            10,
        ):
            result = _derive_pipeline_state(
                total_files=5,
                tagged_count=5,
                untagged_count=0,
                calibrated_count=5,
                written_count=5,
            )

        assert result == PIPELINE_TOO_SMALL

    @pytest.mark.unit
    def test_returns_awaiting_calibration_when_calibration_is_incomplete(self) -> None:
        """Returns awaiting_calibration once enough files are tagged but not calibrated."""
        with patch(
            "nomarr.services.infrastructure.config_svc.INTERNAL_CALIBRATION_MIN_FILES",
            10,
        ):
            result = _derive_pipeline_state(
                total_files=10,
                tagged_count=10,
                untagged_count=0,
                calibrated_count=9,
                written_count=9,
            )

        assert result == PIPELINE_AWAITING_CALIBRATION

    @pytest.mark.unit
    def test_returns_write_ready_when_calibrated_but_not_written(self) -> None:
        """Returns write_ready after calibration is complete and writes are pending."""
        with patch(
            "nomarr.services.infrastructure.config_svc.INTERNAL_CALIBRATION_MIN_FILES",
            10,
        ):
            result = _derive_pipeline_state(
                total_files=10,
                tagged_count=10,
                untagged_count=0,
                calibrated_count=10,
                written_count=9,
            )

        assert result == PIPELINE_WRITE_READY

    @pytest.mark.unit
    def test_returns_done_when_all_pipeline_steps_are_complete(self) -> None:
        """Returns done when tagging, calibration, and writes are complete."""
        with patch(
            "nomarr.services.infrastructure.config_svc.INTERNAL_CALIBRATION_MIN_FILES",
            10,
        ):
            result = _derive_pipeline_state(
                total_files=10,
                tagged_count=10,
                untagged_count=0,
                calibrated_count=10,
                written_count=10,
            )

        assert result == PIPELINE_DONE


class TestUpgrade:
    """Tests for upgrade()."""

    @pytest.mark.unit
    def test_skips_state_derivation_when_required_collections_missing(self) -> None:
        """Skips initial state derivation when a required collection is missing."""
        mock_db = MagicMock()
        mock_db.aql.execute = MagicMock()

        def has_collection_side_effect(name: str) -> bool:
            return name in {
                "library_pipeline_states",
                "library_has_pipeline_state",
                "libraries",
                "file_has_state",
            }

        mock_db.has_collection.side_effect = has_collection_side_effect
        mock_db.has_graph.return_value = True
        mock_graph = MagicMock()
        mock_graph.has_edge_definition.return_value = True
        mock_db.graph.return_value = mock_graph

        upgrade(mock_db)

        assert mock_db.aql.execute.call_count == 1
        executed_query = mock_db.aql.execute.call_args_list[0].args[0]
        assert "library_auto_write" in executed_query
        assert all("LET file_ids =" not in call.args[0] for call in mock_db.aql.execute.call_args_list)

    @pytest.mark.unit
    def test_creates_collections_and_graph_on_fresh_install(self) -> None:
        """Creates the pipeline collections and graph on a fresh install."""
        mock_db = MagicMock()
        created_collections: set[str] = set()

        def has_collection_side_effect(name: str) -> bool:
            return name in created_collections

        def create_collection_side_effect(name: str, edge: bool = False) -> MagicMock:
            created_collections.add(name)
            return MagicMock()

        mock_db.has_collection.side_effect = has_collection_side_effect
        mock_db.has_graph.return_value = False
        mock_db.create_collection.side_effect = create_collection_side_effect
        mock_db.create_graph.return_value = MagicMock()
        mock_collection = MagicMock()
        mock_db.collection.return_value = mock_collection

        upgrade(mock_db)

        assert mock_db.create_collection.call_count >= 2
        mock_db.create_collection.assert_any_call("library_pipeline_states")
        mock_db.create_collection.assert_any_call("library_has_pipeline_state", edge=True)
        mock_db.create_graph.assert_called_once()

    @pytest.mark.unit
    def test_derives_initial_states_for_libraries_without_edges(self) -> None:
        """Derives and inserts initial states for libraries without state edges."""
        mock_db = MagicMock()

        def has_collection_side_effect(name: str) -> bool:
            return name in {
                "library_pipeline_states",
                "library_has_pipeline_state",
                "libraries",
                "library_contains_file",
                "file_has_state",
            }

        mock_db.has_collection.side_effect = has_collection_side_effect
        mock_db.has_graph.return_value = True
        mock_graph = MagicMock()
        mock_graph.has_edge_definition.return_value = True
        mock_graph.replace_edge_definition.return_value = MagicMock()
        mock_db.graph.return_value = mock_graph
        mock_db.collection.return_value = MagicMock()
        mock_db.aql.execute.side_effect = [
            MagicMock(),
            iter(
                [
                    {
                        "library_id": "libraries/1",
                        "has_state_edge": False,
                        "total_files": 0,
                        "tagged_count": 0,
                        "untagged_count": 0,
                        "calibrated_count": 0,
                        "written_count": 0,
                    }
                ]
            ),
            MagicMock(),
        ]

        upgrade(mock_db)

        assert mock_db.aql.execute.call_count == 3
        insert_call = mock_db.aql.execute.call_args_list[2]
        assert insert_call.kwargs["bind_vars"]["library_id"] == "libraries/1"
        assert insert_call.kwargs["bind_vars"]["target_state"] == "library_pipeline_states/idle"

    @pytest.mark.unit
    def test_skips_libraries_that_already_have_state_edges(self) -> None:
        """Skips inserting derived states for libraries that already have state edges."""
        mock_db = MagicMock()

        def has_collection_side_effect(name: str) -> bool:
            return name in {
                "library_pipeline_states",
                "library_has_pipeline_state",
                "libraries",
                "library_contains_file",
                "file_has_state",
            }

        mock_db.has_collection.side_effect = has_collection_side_effect
        mock_db.has_graph.return_value = True
        mock_graph = MagicMock()
        mock_graph.has_edge_definition.return_value = True
        mock_graph.replace_edge_definition.return_value = MagicMock()
        mock_db.graph.return_value = mock_graph
        mock_db.collection.return_value = MagicMock()
        mock_db.aql.execute.side_effect = [
            MagicMock(),
            iter(
                [
                    {
                        "library_id": "libraries/1",
                        "has_state_edge": True,
                        "total_files": 0,
                        "tagged_count": 0,
                        "untagged_count": 0,
                        "calibrated_count": 0,
                        "written_count": 0,
                    }
                ]
            ),
        ]

        upgrade(mock_db)

        assert mock_db.aql.execute.call_count == 2
