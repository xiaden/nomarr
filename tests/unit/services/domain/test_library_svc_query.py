"""Tests for nomarr.services.domain.library_svc.query module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.helpers.dto.library_dto import LibraryDict, LibraryStatsResult
from nomarr.services.domain.library_svc.query import LibraryQueryMixin


class _ConcreteQueryMixin(LibraryQueryMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.cfg = MagicMock()


class TestGetLibraryStats:
    """Tests for get_library_stats."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_library_stats_result(self) -> None:
        mock_db = MagicMock()
        stats = {
            "total_files": 100,
            "total_artists": 10,
            "total_albums": 5,
            "total_duration": 36000,
            "total_size": 500_000_000,
            "needs_tagging_count": 3,
        }
        mixin = _ConcreteQueryMixin(mock_db)

        with patch("nomarr.services.domain.library_svc.query.get_library_stats", return_value=stats) as mock_stats:
            result = await mixin.get_library_stats()

        assert isinstance(result, LibraryStatsResult)
        assert result.total_files == 100
        assert result.needs_tagging_count == 3
        mock_stats.assert_called_once_with(mock_db)


class TestGetTaggedLibraryPaths:
    """Tests for get_tagged_library_paths."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_delegates_to_library_files(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        expected = ["/music/song1.mp3", "/music/song2.mp3"]

        with patch(
            "nomarr.services.domain.library_svc.query.get_tagged_file_paths",
            return_value=expected,
        ) as mock_paths:
            result = await mixin.get_tagged_library_paths()

        assert result == expected
        mock_paths.assert_called_once_with(mock_db)


class TestGetPathsNeedingCalibration:
    """Tests for get_paths_needing_calibration."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_libraries_returns_empty(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with patch("nomarr.services.domain.library_svc.query.list_library_records", return_value=[]):
            result = await mixin.get_paths_needing_calibration()

        assert result == []

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_uncalibrated_files_returns_empty(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[
                    LibraryDict(
                        id=1,
                        name="L1",
                        root_path="/p1",
                        is_enabled=True,
                        created_at=0,
                        updated_at=0,
                    )
                ],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_uncalibrated_tagged_file_ids",
                return_value=[],
            ) as mock_uncalibrated,
        ):
            result = await mixin.get_paths_needing_calibration()

        assert result == []
        mock_uncalibrated.assert_called_once_with(mock_db, 1)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_uncalibrated_files_resolves_to_paths(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[
                    LibraryDict(
                        id=1,
                        name="L1",
                        root_path="/p1",
                        is_enabled=True,
                        created_at=0,
                        updated_at=0,
                    )
                ],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_uncalibrated_tagged_file_ids",
                return_value=[f"{'library_files'}/a", f"{'library_files'}/b"],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_files_by_ids_with_tags",
                return_value=[{"path": "/music/song1.mp3"}, {"path": "/music/song2.mp3"}],
            ) as mock_files,
        ):
            result = await mixin.get_paths_needing_calibration()

        assert result == ["/music/song1.mp3", "/music/song2.mp3"]
        mock_files.assert_called_once_with(mock_db, [f"{'library_files'}/a", f"{'library_files'}/b"])


class TestGetErroredFiles:
    """Tests for get_errored_files."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_errored_files_result(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch.object(
                mixin,
                "_get_library_or_error",
                return_value={"_id": 123},
            ),
            patch(
                "nomarr.services.domain.library_svc.query.count_errored_files",
                return_value=2,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_errored_file_ids",
                return_value=[f"{'library_files'}/1", f"{'library_files'}/2"],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_files_by_ids_with_tags",
                return_value=[
                    {
                        "id": 1,
                        "path": "/music/song1.mp3",
                        "duration_seconds": 180,
                        "artist": "Artist A",
                        "title": "Song 1",
                    },
                    {
                        "id": 2,
                        "path": "/music/song2.mp3",
                        "duration_seconds": 200,
                        "artist": "Artist B",
                        "title": "Song 2",
                    },
                ],
            ),
        ):
            result = await mixin.get_errored_files(123)

        assert result["total"] == 2
        assert len(result["files"]) == 2
        assert result["files"][0]["id"] == 1
        assert result["files"][1]["path"] == "/music/song2.mp3"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        with (
            patch.object(mixin, "_get_library_or_error", side_effect=ValueError("not found")),
            pytest.raises(ValueError, match="not found"),
        ):
            await mixin.get_errored_files("bad_id")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_empty_when_no_errored_files(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch.object(
                mixin,
                "_get_library_or_error",
                return_value={"_id": 123},
            ),
            patch(
                "nomarr.services.domain.library_svc.query.count_errored_files",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_errored_file_ids",
                return_value=[],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_files_by_ids_with_tags",
                return_value=[],
            ),
        ):
            result = await mixin.get_errored_files(123)

        assert result["total"] == 0
        assert result["files"] == []


class TestGetWorkStatus:
    """Tests for LibraryQueryMixin.get_work_status."""

    def _make_stats(self) -> LibraryStatsResult:
        return LibraryStatsResult(
            total_files=100,
            total_artists=5,
            total_albums=10,
            total_duration=36000,
            total_size=500_000_000,
            needs_tagging_count=0,
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_work_status_result(self) -> None:
        """Should return a WorkStatusResult instance."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = AsyncMock(return_value={})
        mock_db.library.count_recently_tagged = AsyncMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[
                    LibraryDict(
                        id=1,
                        name="Rock Library",
                        root_path="/music",
                        is_enabled=True,
                        created_at=0,
                        updated_at=0,
                        library_auto_write=False,
                    )
                ],
            ),
            patch.object(
                LibraryQueryMixin,
                "get_library_stats",
                return_value=self._make_stats(),
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_libraries_in_axis_state",
                return_value=[],
            ),
        ):
            result = await mixin.get_work_status()

        assert isinstance(result, WorkStatusResult)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_pipeline_states_bulk_fetched(self) -> None:
        """Library in not_written tag_write state maps to state='write_ready' in result."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = AsyncMock(return_value={})
        mock_db.library.count_recently_tagged = AsyncMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        def _state_side_effect(_db: MagicMock, axis_field: str, axis_value: str) -> list[str]:
            if axis_field == "tag_write_state" and axis_value == "not_written":
                return ["1"]
            return []

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[
                    LibraryDict(
                        id=1,
                        name="Rock Library",
                        root_path="/music",
                        is_enabled=True,
                        created_at=0,
                        updated_at=0,
                        library_auto_write=False,
                    )
                ],
            ),
            patch.object(
                LibraryQueryMixin,
                "get_library_stats",
                return_value=self._make_stats(),
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_libraries_in_axis_state",
                side_effect=_state_side_effect,
            ),
        ):
            result = await mixin.get_work_status()

        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].state == "write_ready"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_libraries_returns_empty_pipeline(self) -> None:
        """Empty library list produces empty pipeline_libraries."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = AsyncMock(return_value={})
        mock_db.library.count_recently_tagged = AsyncMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[],
            ),
            patch.object(
                LibraryQueryMixin,
                "get_library_stats",
                return_value=LibraryStatsResult(
                    total_files=0,
                    total_artists=0,
                    total_albums=0,
                    total_duration=0,
                    total_size=0,
                    needs_tagging_count=0,
                ),
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_libraries_in_axis_state",
                return_value=[],
            ),
        ):
            result = await mixin.get_work_status()

        assert result.pipeline_libraries == []
