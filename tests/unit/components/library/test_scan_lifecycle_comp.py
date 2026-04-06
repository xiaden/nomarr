"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.scan_lifecycle_comp import (
    bootstrap_file_state_edges,
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
