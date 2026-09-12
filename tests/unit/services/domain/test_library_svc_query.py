"""Tests for nomarr.services.domain.library_svc.query module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import TaggedSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.helpers.dto.library_dto import LibraryDict, LibraryStatsResult
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.services.domain.library_svc.query import LibraryQueryMixin


class _ConcreteQueryMixin(LibraryQueryMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.cfg = MagicMock()


def _make_library(*, name: str = "L1") -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name=name, root_path="/p1", is_enabled=True)


def _song(*, path: str, duration_seconds: float | None = None) -> Song:
    """Build a minimal semantic ``Song`` fixture."""
    return Song(
        path=path,
        normalized_path=path.lstrip("/"),
        file_size=0,
        modified_time=0,
        duration_seconds=duration_seconds,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=0,
    )


def _locator(*, library_uuid: str, normalized_path: str) -> SongIdentity:
    """Build a semantic ``SongIdentity`` locator fixture."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid=library_uuid, name="L1", root_path="/p1"),
        normalized_path=normalized_path,
    )


def _tagged_song(*, path: str, metadata: dict[str, object], duration_seconds: float | None = None) -> TaggedSong:
    """Build a semantic ``TaggedSong`` carrier fixture."""
    return TaggedSong(song=_song(path=path, duration_seconds=duration_seconds), metadata=metadata, tags=())


class TestGetLibraryStats:
    """Tests for get_library_stats."""

    @pytest.mark.unit
    def test_returns_library_stats_result(self) -> None:
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
            result = mixin.get_library_stats()

        assert isinstance(result, LibraryStatsResult)
        assert result.total_files == 100
        assert result.needs_tagging_count == 3
        mock_stats.assert_called_once_with(mock_db)


class TestGetTaggedLibraryPaths:
    """Tests for get_tagged_library_paths."""

    @pytest.mark.unit
    def test_delegates_to_songs(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        expected = ["/music/song1.mp3", "/music/song2.mp3"]

        with patch(
            "nomarr.services.domain.library_svc.query.get_tagged_file_paths",
            return_value=expected,
        ) as mock_paths:
            result = mixin.get_tagged_library_paths()

        assert result == expected
        mock_paths.assert_called_once_with(mock_db)


class TestGetPathsNeedingCalibration:
    """Tests for get_paths_needing_calibration."""

    @pytest.mark.unit
    def test_no_libraries_returns_empty(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)

        with patch("nomarr.services.domain.library_svc.query.list_all_libraries", return_value=[]):
            result = mixin.get_paths_needing_calibration()

        assert result == []

    @pytest.mark.unit
    def test_no_uncalibrated_files_returns_empty(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        library = _make_library()

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_all_libraries",
                return_value=[library],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_uncalibrated_tagged_song_ids",
                return_value=[],
            ) as mock_uncalibrated,
        ):
            result = mixin.get_paths_needing_calibration()

        assert result == []
        mock_uncalibrated.assert_called_once_with(mock_db, library)

    @pytest.mark.unit
    def test_uncalibrated_files_resolves_to_paths(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        library = _make_library()
        locator_a = _locator(library_uuid="2621ebfb-71ff-4168-a812-5342ca310e8c", normalized_path="songs/a")
        locator_b = _locator(library_uuid="5f0c1b2a-3d4e-4f60-8a91-b2c3d4e5f607", normalized_path="songs/b")
        mock_db.library.get_song = MagicMock(
            side_effect=[
                _song(path="/music/song1.mp3"),
                _song(path="/music/song2.mp3"),
            ]
        )

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_all_libraries",
                return_value=[library],
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_uncalibrated_tagged_song_ids",
                return_value=[locator_a, locator_b],
            ) as mock_uncalibrated,
        ):
            result = mixin.get_paths_needing_calibration()

        assert result == ["/music/song1.mp3", "/music/song2.mp3"]
        mock_uncalibrated.assert_called_once_with(mock_db, library)
        assert [call.args[0] for call in mock_db.library.get_song.call_args_list] == [locator_a, locator_b]


class TestGetErroredFiles:
    """Tests for get_errored_files."""

    @pytest.mark.unit
    def test_returns_errored_files_result(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        library = _make_library()

        locator_1 = _locator(library_uuid="2621ebfb-71ff-4168-a812-5342ca310e8c", normalized_path="songs/1")
        locator_2 = _locator(library_uuid="5f0c1b2a-3d4e-4f60-8a91-b2c3d4e5f607", normalized_path="songs/2")
        carriers = [
            _tagged_song(
                path="/music/song1.mp3",
                metadata={"artist": "Artist A", "title": "Song 1"},
                duration_seconds=180,
            ),
            _tagged_song(
                path="/music/song2.mp3",
                metadata={"artist": "Artist B", "title": "Song 2"},
                duration_seconds=200,
            ),
        ]

        with (
            patch.object(
                mixin,
                "_get_library_or_error",
                return_value=library,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.count_errored_songs",
                return_value=2,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_errored_song_ids",
                return_value=[locator_1, locator_2],
            ),
            patch.object(mixin, "_songs_for_locators", return_value=carriers),
        ):
            result = mixin.get_errored_files(library)

        assert result["total"] == 2
        assert len(result["files"]) == 2
        # file_id is an opaque nom1 SongLocator token, never a generated integer id.
        assert result["files"][0]["file_id"] == encode_song_locator(locator_1)
        assert result["files"][1]["file_id"] == encode_song_locator(locator_2)
        assert result["files"][0]["artist"] == "Artist A"
        assert result["files"][1]["path"] == "/music/song2.mp3"

    @pytest.mark.unit
    def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        with (
            patch.object(mixin, "_get_library_or_error", side_effect=ValueError("not found")),
            pytest.raises(ValueError, match="not found"),
        ):
            mixin.get_errored_files(_make_library())

    @pytest.mark.unit
    def test_returns_empty_when_no_errored_files(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteQueryMixin(mock_db)
        library = _make_library()

        with (
            patch.object(
                mixin,
                "_get_library_or_error",
                return_value=library,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.count_errored_songs",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.library_svc.query.get_errored_song_ids",
                return_value=[],
            ),
        ):
            result = mixin.get_errored_files(library)

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

    def _make_library_doc(self) -> LibraryDict:
        """Build a ``LibraryDict`` transport projection (no storage PK / timestamps)."""
        return LibraryDict(
            name="Rock Library",
            root_path="/music",
            is_enabled=True,
            library_auto_write=False,
        )

    @pytest.mark.unit
    def test_returns_work_status_result(self) -> None:
        """Should return a WorkStatusResult instance."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = MagicMock(return_value={})
        mock_db.library.count_recently_tagged = MagicMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[self._make_library_doc()],
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
            result = mixin.get_work_status()

        assert isinstance(result, WorkStatusResult)

    @pytest.mark.unit
    def test_pipeline_states_bulk_fetched(self) -> None:
        """Library in not_written tag_write state maps to state='write_ready' in result."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = MagicMock(return_value={})
        mock_db.library.count_recently_tagged = MagicMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        def _state_side_effect(_db: MagicMock, axis_field: str, axis_value: str) -> list[Library]:
            # get_libraries_in_axis_state returns domain Libraries; names key the
            # per-library pipeline states.
            if axis_field == "tag_write_state" and axis_value == "not_written":
                return [_make_library(name="Rock Library")]
            return []

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[self._make_library_doc()],
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
            result = mixin.get_work_status()

        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].state == "write_ready"

    @pytest.mark.unit
    def test_no_libraries_returns_empty_pipeline(self) -> None:
        """Empty library list produces empty pipeline_libraries."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = MagicMock(return_value={})
        mock_db.library.count_recently_tagged = MagicMock(return_value=0)
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
            result = mixin.get_work_status()

        assert result.pipeline_libraries == []

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("axis_field", "axis_value", "expected_state"),
        [
            ("scan_state", "scanning", "scanning"),
            ("ml_state", "ML_processing", "ml_running"),
            ("calibration_state", "calibrating", "calibrating"),
            ("tag_write_state", "writing", "writing"),
        ],
    )
    def test_active_pole_propagates_and_marks_busy(
        self,
        axis_field: str,
        axis_value: str,
        expected_state: str,
    ) -> None:
        """Any single active (in-progress) pole propagates and yields busy semantics."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = MagicMock(return_value={})
        mock_db.library.count_recently_tagged = MagicMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        def _state_side_effect(_db: MagicMock, current_axis: str, current_value: str) -> list[Library]:
            if current_axis == axis_field and current_value == axis_value:
                return [_make_library(name="Rock Library")]
            return []

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[self._make_library_doc()],
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
            result = mixin.get_work_status()

        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].state == expected_state
        assert result.is_busy is True

    @pytest.mark.unit
    def test_axis_in_progress_states_propagate(self) -> None:
        """In-progress calibration and write poles reach pipeline states (not terminal)."""
        mock_db = MagicMock()
        mock_db.app.get_file_query_stats = MagicMock(return_value={})
        mock_db.library.count_recently_tagged = MagicMock(return_value=0)
        mixin = _ConcreteQueryMixin(mock_db)

        def _state_side_effect(_db: MagicMock, axis_field: str, axis_value: str) -> list[Library]:
            if axis_field == "calibration_state" and axis_value == "calibrating":
                return [_make_library(name="Rock Library")]
            if axis_field == "tag_write_state" and axis_value == "writing":
                return [_make_library(name="Rock Library")]
            return []

        with (
            patch(
                "nomarr.services.domain.library_svc.query.list_library_records",
                return_value=[self._make_library_doc()],
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
            result = mixin.get_work_status()

        assert len(result.pipeline_libraries) == 1
        # _derive_pipeline_state reports the first incomplete axis: calibrating.
        assert result.pipeline_libraries[0].state == "calibrating"
        assert result.is_busy is True
