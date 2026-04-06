"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.scan_lifecycle_comp import (
    bootstrap_file_state_edges,
    get_library_scan_histories,
    get_scanning_library_ids,
    is_library_scanning,
)
from nomarr.persistence.database.library_pipeline_states_aql import PIPELINE_SCANNING


class TestBootstrapFileStateEdges:
    """Tests for bootstrap_file_state_edges."""

    @pytest.mark.unit
    def test_empty_bootstraps_returns_zero(self) -> None:
        mock_db = MagicMock()
        result = bootstrap_file_state_edges(mock_db, [], {})
        assert result == 0

    @pytest.mark.unit
    def test_ml_tagged_type_creates_edge_via_set_tagged(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 1
        mock_db.file_states.set_tagged.assert_called_once_with("library_files/abc")

    @pytest.mark.unit
    def test_unknown_bootstrap_type_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "unknown_type"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.file_states.set_tagged.assert_not_called()

    @pytest.mark.unit
    def test_file_not_in_file_id_by_path_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/missing.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/other.mp3": "library_files/xyz"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.file_states.set_tagged.assert_not_called()


class TestIsLibraryScanning:
    """Tests for is_library_scanning."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_get_state_raises_value_error(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.library_pipeline_states.get_state.side_effect = ValueError()

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.library_pipeline_states.get_state.assert_called_once_with(library_id)


class TestGetScanningLibraryIds:
    """Tests for get_scanning_library_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_scanning_state_query_and_returns_set(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = [
            "libraries/one",
            "libraries/two",
            "libraries/one",
        ]

        result = get_scanning_library_ids(mock_db)

        assert result == {"libraries/one", "libraries/two"}
        assert isinstance(result, set)
        mock_db.library_pipeline_states.get_libraries_in_state.assert_called_once_with(
            PIPELINE_SCANNING,
        )


class TestGetLibraryScanHistories:
    """Tests for get_library_scan_histories."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_scan_history_for_all_libraries(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {
                "_id": "libraries/one",
                "name": "Main Library",
                "scanned_at": 123,
                "scan_status": "complete",
                "ignored": "value",
            },
            {
                "_id": "libraries/two",
                "scanned_at": None,
            },
        ]

        result = get_library_scan_histories(mock_db)

        assert result == [
            {
                "library_id": "libraries/one",
                "name": "Main Library",
                "scanned_at": 123,
                "scan_status": "complete",
            },
            {
                "library_id": "libraries/two",
                "name": "Unknown",
                "scanned_at": None,
                "scan_status": "idle",
            },
        ]
        mock_db.libraries.list_libraries.assert_called_once_with(enabled_only=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_limit_before_projection(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/one", "name": "One", "scan_status": "idle"},
            {"_id": "libraries/two", "name": "Two", "scan_status": "scanning"},
            {"_id": "libraries/three", "name": "Three", "scan_status": "complete"},
        ]

        result = get_library_scan_histories(mock_db, limit=2)

        assert result == [
            {
                "library_id": "libraries/one",
                "name": "One",
                "scanned_at": None,
                "scan_status": "idle",
            },
            {
                "library_id": "libraries/two",
                "name": "Two",
                "scanned_at": None,
                "scan_status": "scanning",
            },
        ]
        mock_db.libraries.list_libraries.assert_called_once_with(enabled_only=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_pipeline_state_is_scanning(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        scanning_key = PIPELINE_SCANNING.rsplit("/", maxsplit=1)[-1]
        mock_db.library_pipeline_states.get_state.return_value = scanning_key

        result = is_library_scanning(mock_db, library_id)

        assert result is True
        mock_db.library_pipeline_states.get_state.assert_called_once_with(library_id)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_pipeline_state_is_not_scanning(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.library_pipeline_states.get_state.return_value = "idle"

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.library_pipeline_states.get_state.assert_called_once_with(library_id)
