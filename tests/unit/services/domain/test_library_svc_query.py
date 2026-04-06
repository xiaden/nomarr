"""Tests for nomarr.services.domain.library_svc.query module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.helpers.dto.library_dto import LibraryStatsResult
from nomarr.services.domain.library_svc.query import LibraryQueryMixin


class _ConcreteQueryMixin(LibraryQueryMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.cfg = MagicMock()


class TestGetLibraryStats:
    """Tests for get_library_stats."""

    @pytest.mark.unit
    def test_returns_library_stats_result(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get_library_stats.return_value = {
            "total_files": 100,
            "total_artists": 10,
            "total_albums": 5,
            "total_duration": 36000,
            "total_size": 500_000_000,
            "needs_tagging_count": 3,
        }
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_library_stats()
        assert isinstance(result, LibraryStatsResult)
        assert result.total_files == 100
        assert result.needs_tagging_count == 3
        mock_db.library_files.get_library_stats.assert_called_once()


class TestGetTaggedLibraryPaths:
    """Tests for get_tagged_library_paths."""

    @pytest.mark.unit
    def test_delegates_to_library_files(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get_tagged_file_paths.return_value = [
            "/music/song1.mp3",
            "/music/song2.mp3",
        ]
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_tagged_library_paths()
        assert result == ["/music/song1.mp3", "/music/song2.mp3"]
        mock_db.library_files.get_tagged_file_paths.assert_called_once()


class TestGetPathsNeedingCalibration:
    """Tests for get_paths_needing_calibration."""

    @pytest.mark.unit
    def test_no_libraries_returns_empty(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = []
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_paths_needing_calibration()
        assert result == []

    @pytest.mark.unit
    def test_no_uncalibrated_files_returns_empty(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1"},
        ]
        mock_db.file_states.get_uncalibrated_tagged_file_ids.return_value = []
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_paths_needing_calibration()
        assert result == []
        mock_db.file_states.get_uncalibrated_tagged_file_ids.assert_called_once_with(
            "libraries/1",
        )

    @pytest.mark.unit
    def test_uncalibrated_files_resolves_to_paths(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1"},
        ]
        mock_db.file_states.get_uncalibrated_tagged_file_ids.return_value = [
            "library_files/a",
            "library_files/b",
        ]
        mock_db.library_files.get_files_by_ids_with_tags.return_value = [
            {"path": "/music/song1.mp3"},
            {"path": "/music/song2.mp3"},
        ]
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_paths_needing_calibration()
        assert result == ["/music/song1.mp3", "/music/song2.mp3"]
        mock_db.library_files.get_files_by_ids_with_tags.assert_called_once_with(
            ["library_files/a", "library_files/b"],
        )


class TestGetErroredFiles:
    """Tests for get_errored_files."""

    @pytest.mark.unit
    def test_returns_errored_files_result(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.count_errored_files.return_value = 2
        mock_db.file_states.get_errored_file_ids.return_value = [
            "library_files/1",
            "library_files/2",
        ]
        mock_db.library_files.get_files_by_ids_with_tags.return_value = [
            {
                "_id": "library_files/1",
                "path": "/music/song1.mp3",
                "duration_seconds": 180,
                "artist": "Artist A",
                "title": "Song 1",
            },
            {
                "_id": "library_files/2",
                "path": "/music/song2.mp3",
                "duration_seconds": 200,
                "artist": "Artist B",
                "title": "Song 2",
            },
        ]
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_errored_files("abc123")
        assert result["total"] == 2
        assert len(result["files"]) == 2
        assert result["files"][0]["_id"] == "library_files/1"
        assert result["files"][1]["path"] == "/music/song2.mp3"

    @pytest.mark.unit
    def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        mixin._get_library_or_error = MagicMock(side_effect=ValueError("not found"))
        with pytest.raises(ValueError, match="not found"):
            mixin.get_errored_files("bad_id")

    @pytest.mark.unit
    def test_returns_empty_when_no_errored_files(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.count_errored_files.return_value = 0
        mock_db.file_states.get_errored_file_ids.return_value = []
        mock_db.library_files.get_files_by_ids_with_tags.return_value = []
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_errored_files("abc123")
        assert result["total"] == 0
        assert result["files"] == []

class TestGetWorkStatus:
    """Tests for LibraryQueryMixin.get_work_status."""

    def _make_db_mock(self) -> MagicMock:
        """Build a mock DB with sensible defaults for get_work_status calls."""
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1", "name": "Rock Library", "library_auto_write": False},
        ]
        mock_db.library_files.get_library_stats.return_value = {
            "total_files": 100,
            "total_artists": 5,
            "total_albums": 10,
            "total_duration": 36000,
            "total_size": 500_000_000,
            "needs_tagging_count": 0,
        }
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = []
        return mock_db

    @pytest.mark.unit
    def test_returns_work_status_result(self) -> None:
        """Should return a WorkStatusResult instance."""
        mock_db = self._make_db_mock()
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_work_status()
        assert isinstance(result, WorkStatusResult)

    @pytest.mark.unit
    def test_pipeline_states_bulk_fetched(self) -> None:
        """Library in write_ready state registry maps to state='write_ready' in result."""
        mock_db = self._make_db_mock()

        def _state_side_effect(doc_id: str) -> list[str]:
            if doc_id == "library_pipeline_states/write_ready":
                return ["libraries/1"]
            return []

        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = _state_side_effect
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_work_status()
        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].state == "write_ready"

    @pytest.mark.unit
    def test_no_libraries_returns_empty_pipeline(self) -> None:
        """Empty library list produces empty pipeline_libraries."""
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = []
        mock_db.library_files.get_library_stats.return_value = {
            "total_files": 0,
            "total_artists": 0,
            "total_albums": 0,
            "total_duration": 0,
            "total_size": 0,
            "needs_tagging_count": 0,
        }
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = []
        mixin = _ConcreteQueryMixin(mock_db)
        result = mixin.get_work_status()
        assert result.pipeline_libraries == []
