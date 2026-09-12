"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_scan_file_ops_comp import (
    _upsert_batch,
    bootstrap_file_state_edges,
    cleanup_stale_folders,
    remove_deleted_files,
    save_folder_record,
    snapshot_existing_files,
    upsert_scanned_files,
)
from nomarr.components.library.library_scan_state_comp import get_scan_state
from nomarr.components.library.scan_lifecycle_comp import (
    LibraryNotFoundError,
    check_interrupted_scan,
    get_library_scan_histories,
    get_scanning_library_ids,
    is_library_scanning,
    is_scan_stale,
    mark_scan_completed,
    mark_scan_started,
    on_scan_complete_pipeline_hook,
    resolve_library_for_scan,
    transition_to_scanning,
    update_scan_progress,
)
from nomarr.components.library.song_query_types import HydratedSong
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.constants.pipeline_states import (
    CAL_NOT_CALIBRATED,
    ML_IN_PROGRESS,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
    WRITE_NOT_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import (
    LibraryFolder,
    LibraryPipelineState,
    LibraryScan,
)
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongRemoval,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.library_dto import LibraryDict


def _library(name: str = "Main", root_path: str = "/tmp") -> Library:
    """Build a domain ``Library`` value (natural identity, no generated id)."""
    return Library(
        name=name,
        root_path=root_path,
        library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
        created_at=None,
        updated_at=None,
    )


def _song(**overrides: object) -> Song:
    base: dict = {
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


def _identity(normalized_path: str = "song.mp3") -> SongIdentity:
    """Semantic song locator used for state-candidate test doubles."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="Main", root_path="/tmp"),
        normalized_path=normalized_path,
    )


class TestBootstrapFileStateEdges:
    """Tests for bootstrap_file_state_edges."""

    @pytest.mark.unit
    def test_empty_bootstraps_returns_zero(self) -> None:
        mock_db = MagicMock()
        result = bootstrap_file_state_edges(mock_db, [], {})
        assert result == 0

    @pytest.mark.unit
    def test_ml_tagged_type_creates_edge_via_transition(self) -> None:
        """A ``ml_tagged`` bootstrap transitions the song out of not-processed."""
        mock_db = MagicMock()
        bootstraps = [{"normalized_path": "/music/song.mp3", "type": "ml_tagged"}]
        identity = _identity("/music/song.mp3")
        song_by_path = {"/music/song.mp3": identity}

        result = bootstrap_file_state_edges(mock_db, bootstraps, song_by_path)

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with([identity], STATE_NOT_PROCESSED, STATE_PROCESSED)

    @pytest.mark.unit
    def test_unknown_bootstrap_type_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "unknown_type"},
        ]
        song_by_path = {"/music/song.mp3": _identity("/music/song.mp3")}
        result = bootstrap_file_state_edges(mock_db, bootstraps, song_by_path)
        assert result == 0
        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_file_not_in_file_id_by_path_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/missing.mp3", "type": "ml_tagged"},
        ]
        song_by_path = {"/music/other.mp3": _identity("/music/other.mp3")}
        result = bootstrap_file_state_edges(mock_db, bootstraps, song_by_path)
        assert result == 0
        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()


class TestIsLibraryScanning:
    """Tests for is_library_scanning."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_get_state_raises_value_error(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.side_effect = ValueError("no pipeline state")

        result = is_library_scanning(mock_db, library)

        assert result is False
        mock_db.library.get_pipeline_state.assert_called_once_with(library)


class TestGetScanningLibraryIds:
    """Tests for get_scanning_library_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_deduplicated_libraries_by_name(self) -> None:
        mock_db = MagicMock()
        lib_one = _library(name="lib-1")
        lib_two = _library(name="lib-2")

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.get_libraries_in_axis_state",
            return_value=[lib_one, lib_two, lib_one],
        ) as mock_get_libraries:
            result = get_scanning_library_ids(mock_db)

        assert isinstance(result, list)
        assert len(result) == 2
        assert {lib.name for lib in result} == {"lib-1", "lib-2"}
        mock_get_libraries.assert_called_once_with(mock_db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


class TestGetLibraryScanHistories:
    """Tests for get_library_scan_histories."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_scan_history_for_all_libraries(self) -> None:
        mock_db = MagicMock()
        lib_one = LibraryDict(
            name="Main Library",
            root_path="/tmp",
            is_enabled=True,
            scanned_at=123,
            scan_status="complete",
        )
        lib_two = LibraryDict(
            name="Lib",
            root_path="/tmp",
            is_enabled=True,
            scanned_at=None,
            scan_status="idle",
        )
        libraries = [lib_one, lib_two]

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.list_library_records",
            return_value=libraries,
        ):
            result = get_library_scan_histories(mock_db)

        assert result == [
            {
                "library_id": "Main Library",
                "name": "Main Library",
                "scanned_at": 123,
                "scan_status": "complete",
            },
            {
                "library_id": "Lib",
                "name": "Lib",
                "scanned_at": None,
                "scan_status": "idle",
            },
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_limit_before_projection(self) -> None:
        mock_db = MagicMock()
        libraries = [
            LibraryDict(
                name="One",
                root_path="/tmp",
                is_enabled=True,
                scanned_at=None,
                scan_status="idle",
            ),
            LibraryDict(
                name="Two",
                root_path="/tmp",
                is_enabled=True,
                scanned_at=None,
                scan_status="idle",
            ),
            LibraryDict(
                name="Three",
                root_path="/tmp",
                is_enabled=True,
                scanned_at=456,
                scan_status="complete",
            ),
        ]

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.list_library_records",
            return_value=libraries,
        ):
            result = get_library_scan_histories(mock_db, limit=2)

        assert result == [
            {
                "library_id": "One",
                "name": "One",
                "scanned_at": None,
                "scan_status": "idle",
            },
            {
                "library_id": "Two",
                "name": "Two",
                "scanned_at": None,
                "scan_status": "idle",
            },
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_pipeline_state_is_scanning(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state=SCAN_IN_PROGRESS,
            ml_state=ML_NOT_PROCESSED,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )

        result = is_library_scanning(mock_db, library)

        assert result is True
        mock_db.library.get_pipeline_state.assert_called_once_with(library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_pipeline_state_is_not_scanning(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state="scanned",
            ml_state=ML_NOT_PROCESSED,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )

        result = is_library_scanning(mock_db, library)

        assert result is False
        mock_db.library.get_pipeline_state.assert_called_once_with(library)


class TestScanStateHelpers:
    """Tests for constructor-backed scan state orchestration helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_looks_up_scan_doc_by_id_keyword(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_scan.return_value = None

        result = get_scan_state(mock_db, library)

        mock_db.library.get_scan.assert_called_once_with(library)
        mock_db.library.add_scan.assert_not_called()
        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_returns_scan_doc_directly_without_repair(self) -> None:
        mock_db = MagicMock()
        library = _library()
        scan = LibraryScan(scan_type="quick", status="idle", started_at=0)
        mock_db.library.get_scan.return_value = scan

        result = get_scan_state(mock_db, library)

        mock_db.library.get_scan.assert_called_once_with(library)
        mock_db.library.remove_scan.assert_not_called()
        mock_db.library.add_scan.assert_not_called()
        assert result == scan

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mark_scan_started_delegates_to_database_facade(self) -> None:
        mock_db = MagicMock()
        library = _library()

        mark_scan_started(mock_db, library, "full")

        mock_db.library.start_scan.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mark_scan_completed_delegates_to_database_facade(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.return_value = None

        mark_scan_completed(mock_db, library)

        mock_db.library.complete_scan.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_scan_progress_delegates_to_database_facade(self) -> None:
        mock_db = MagicMock()
        library = _library()

        with patch("nomarr.components.library.scan_lifecycle_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 123
            update_scan_progress(mock_db, library, progress=5, total=12, scan_error="boom")

        mock_db.library.record_scan_progress.assert_called_once_with(
            library,
            heartbeat_at=123,
            status=None,
            progress=5,
            total=12,
            scan_error="boom",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_scan_stale_uses_recent_heartbeat(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state=SCAN_IN_PROGRESS,
            ml_state=ML_NOT_PROCESSED,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )
        mock_db.library.get_scan.return_value = LibraryScan(
            scan_type="quick",
            status="in_progress",
            started_at=100,
            heartbeat_at=290_000,
        )

        with patch("nomarr.components.library.scan_lifecycle_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 300_000
            assert is_scan_stale(mock_db, library, timeout_ms=20_000) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_scan_stale_falls_back_to_started_at(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state=SCAN_IN_PROGRESS,
            ml_state=ML_NOT_PROCESSED,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )
        mock_db.library.get_scan.return_value = LibraryScan(
            scan_type="quick",
            status="in_progress",
            started_at=100,
        )

        with patch("nomarr.components.library.scan_lifecycle_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 301
            assert is_scan_stale(mock_db, library, timeout_ms=200) is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_check_interrupted_scan_delegates_to_database_facade(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_scan.return_value = LibraryScan(scan_type="quick", status="in_progress", started_at=0)

        assert check_interrupted_scan(mock_db, library) == (True, "quick")
        mock_db.library.get_scan.assert_called_once_with(library)


class TestFolderCacheHelpers:
    """Tests for constructor-backed folder cache persistence helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_save_folder_record_replaces_existing_doc_via_library_intents(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.list_folders_for_library.return_value = [LibraryFolder(path="Rock")]

        with patch("nomarr.components.library.library_scan_file_ops_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 456
            save_folder_record(mock_db, library, "Rock", 123, 7)

        inserted = mock_db.library.replace_library_folder.call_args.args[2]
        assert isinstance(inserted, LibraryFolder)
        assert inserted.path == "Rock"
        assert inserted.mtime == 123
        assert inserted.file_count == 7
        assert inserted.last_scanned_at == 456
        mock_db.library.replace_library_folder.assert_called_once_with(library, "Rock", inserted)
        mock_db.library.add_library_folder.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_save_folder_record_replaces_matching_path(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.list_folders_for_library.return_value = [LibraryFolder(path="Rock")]

        save_folder_record(mock_db, library, "Rock", 123, 7)

        mock_db.library.replace_library_folder.assert_called_once()
        mock_db.library.add_library_folder.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_save_folder_record_adds_missing_path(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.list_folders_for_library.return_value = []

        save_folder_record(mock_db, library, "Rock", 123, 7)

        mock_db.library.add_library_folder.assert_called_once()
        mock_db.library.replace_library_folder.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cleanup_stale_folders_deletes_only_missing_paths(self) -> None:
        mock_db = MagicMock()
        library = _library()

        with patch(
            "nomarr.components.library.library_scan_file_ops_comp.get_cached_folders",
            return_value={
                "Keep": LibraryFolder(path="Keep"),
                "Drop": LibraryFolder(path="Drop"),
            },
        ):
            cleanup_stale_folders(mock_db, library, {"Keep"})

        mock_db.library.remove_library_folder.assert_called_once_with(library, "Drop")


@pytest.mark.unit
@pytest.mark.mocked
class TestRemoveDeletedFiles:
    """Tests for remove_deleted_files."""

    def test_remove_deleted_files_delegates_cleanup_to_remove_file(self) -> None:
        """remove_deleted_files resolves file ids and delegates deletion to library.remove_song."""
        mock_db = MagicMock()
        library = _library()
        paths = ["/music/a.mp3", "/music/b.mp3", "/music/c.mp3"]
        mock_db.library.get_song_by_path.side_effect = [
            _song(normalized_path="a.mp3"),
            _song(normalized_path="b.mp3"),
            None,
        ]
        library_identity = LibraryIdentity(
            library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="Main", root_path="/tmp"
        )

        result = remove_deleted_files(mock_db, library, paths)

        assert mock_db.library.remove_song.call_args_list == [
            call(SongRemoval(song_identity=SongIdentity(library=library_identity, normalized_path="a.mp3"))),
            call(SongRemoval(song_identity=SongIdentity(library=library_identity, normalized_path="b.mp3"))),
        ]
        assert mock_db.library.get_song_by_path.call_args_list == [
            call("/music/a.mp3", library),
            call("/music/b.mp3", library),
            call("/music/c.mp3", library),
        ]
        assert result == 2

    def test_remove_deleted_files_returns_zero_for_empty_list(self) -> None:
        """remove_deleted_files skips lookup and deletion when no file paths are supplied."""
        mock_db = MagicMock()
        library = _library()

        result = remove_deleted_files(mock_db, library, [])

        mock_db.library.get_song_by_path.assert_not_called()
        mock_db.library.remove_song.assert_not_called()
        assert result == 0

    def test_remove_deleted_files_raises_without_library_uuid(self) -> None:
        """A library with no ``library_uuid`` cannot form a locator: fail closed."""
        mock_db = MagicMock()
        library = Library(
            name="Main",
            root_path="/tmp",
            library_uuid=None,
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=False,
            created_at=None,
            updated_at=None,
        )

        with pytest.raises(ValueError, match="has no library_uuid"):
            remove_deleted_files(mock_db, library, ["/music/a.mp3"])

        mock_db.library.get_song_by_path.assert_not_called()
        mock_db.library.remove_song.assert_not_called()

    def test_remove_deleted_files_counts_only_successful_removals(self) -> None:
        """A falsy ``remove_song`` (stale/missing locator) is not counted as removed."""
        mock_db = MagicMock()
        library = _library()
        mock_db.library.get_song_by_path.side_effect = [
            _song(normalized_path="a.mp3"),
            _song(normalized_path="b.mp3"),
        ]
        mock_db.library.remove_song.side_effect = [False, True]

        result = remove_deleted_files(mock_db, library, ["/music/a.mp3", "/music/b.mp3"])

        assert mock_db.library.remove_song.call_count == 2
        assert result == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertBatch:
    """Tests for ``_upsert_batch`` -- one typed batch facade call for all docs.

    State preservation and create-only initialization are persistence-owned and
    pinned by the real boundary test
    ``tests/integration/test_song_upsert_state_boundary_pg.py``.
    """

    def _doc(self, path: str = "/music/song.mp3", **overrides: object) -> dict:
        base: dict = {
            "path": path,
            "normalized_path": path.lstrip("/"),
            "file_size": 123,
            "modified_time": 456,
            "duration_seconds": 12.5,
            "is_valid": True,
        }
        base.update(overrides)
        return base

    def test_empty_input_returns_empty_without_facade_calls(self) -> None:
        mock_db = MagicMock()
        library = _library()

        result = _upsert_batch(mock_db, library, [])

        assert result == []
        mock_db.library.add_songs_to_library_batch.assert_not_called()

    def test_missing_library_uuid_raises_value_error(self) -> None:
        mock_db = MagicMock()
        library = Library(
            name="Main",
            root_path="/tmp",
            library_uuid=None,
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=False,
            created_at=None,
            updated_at=None,
        )

        with pytest.raises(ValueError, match="has no library_uuid"):
            _upsert_batch(mock_db, library, [self._doc()])

        mock_db.library.add_songs_to_library_batch.assert_not_called()

    def test_docs_map_to_one_atomic_typed_batch_call(self) -> None:
        """All docs go through one typed batch facade call, preserving order.

        State preservation/create-only initialization is owned by the
        persistence intent (covered by the real boundary test in
        ``tests/unit/persistence/api/test_library_db.py``); the component no
        longer reads or repairs state.
        """
        mock_db = MagicMock()
        library = _library()
        identity = _identity("music/song.mp3")
        mock_db.library.add_songs_to_library_batch.return_value = [identity]
        doc = self._doc()

        result = _upsert_batch(mock_db, library, [doc])

        assert result == [identity]
        (commands,), _kwargs = mock_db.library.add_songs_to_library_batch.call_args
        assert len(commands) == 1
        command = commands[0]
        assert isinstance(command, SongUpsertInput)
        assert command.library == LibraryIdentity(
            library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="Main", root_path="/tmp"
        )
        assert command.path == "/music/song.mp3"
        assert command.scan == SongScanUpdate(
            normalized_path="music/song.mp3",
            file_size=123,
            modified_time=456,
            duration_seconds=12.5,
            is_valid=True,
        )

    def test_multiple_docs_are_one_batch_call(self) -> None:
        mock_db = MagicMock()
        library = _library()
        si_a = _identity("music/a.mp3")
        si_b = _identity("music/b.mp3")
        mock_db.library.add_songs_to_library_batch.return_value = [si_a, si_b]
        docs = [self._doc(path="/music/a.mp3"), self._doc(path="/music/b.mp3")]

        result = _upsert_batch(mock_db, library, docs)

        assert result == [si_a, si_b]
        mock_db.library.add_songs_to_library_batch.assert_called_once()
        commands = mock_db.library.add_songs_to_library_batch.call_args.args[0]
        assert [command.path for command in commands] == ["/music/a.mp3", "/music/b.mp3"]


@pytest.mark.unit
@pytest.mark.mocked
class TestResolveLibraryForScan:
    """Tests for library lookup before a scan starts."""

    def test_returns_library_when_lookup_succeeds(self) -> None:
        mock_db = MagicMock()
        library = _library(name="Main")
        persisted = Library(name="Main", root_path="/tmp", created_at=0, updated_at=0)
        mock_db.library.get_library.return_value = persisted

        result = resolve_library_for_scan(mock_db, library)

        assert isinstance(result, Library)
        assert result.name == "Main"
        mock_db.library.get_library.assert_called_once_with(library)

    def test_raises_library_not_found_when_lookup_returns_none(self) -> None:
        mock_db = MagicMock()
        library = _library(name="Missing")
        mock_db.library.get_library.return_value = None

        with pytest.raises(LibraryNotFoundError, match="Library 'Missing' not found"):
            resolve_library_for_scan(mock_db, library)

        mock_db.library.get_library.assert_called_once_with(library)


@pytest.mark.unit
@pytest.mark.mocked
class TestTransitionToScanning:
    """Tests for pipeline transition into scanning."""

    def test_delegates_to_transition_pipeline_axis_with_scanning(self) -> None:
        mock_db = MagicMock()
        library = _library()

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            transition_to_scanning(mock_db, library)

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            library,
            SCAN_STATE_FIELD,
            SCAN_IN_PROGRESS,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestOnScanCompletePipelineHook:
    """Tests for post-scan pipeline state transitions."""

    def test_transitions_ml_axis_when_files_exist(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.list_library_song_ids.return_value = ["file1", "file2"]
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state="scanned",
            ml_state=ML_NOT_PROCESSED,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            on_scan_complete_pipeline_hook(mock_db, library)

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            library,
            ML_STATE_FIELD,
            ML_IN_PROGRESS,
        )

    def test_transitions_ml_axis_when_no_files(self) -> None:
        mock_db = MagicMock()
        library = _library()
        mock_db.library.list_library_song_ids.return_value = []
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state="scanned",
            ml_state=ML_IN_PROGRESS,
            calibration_state=CAL_NOT_CALIBRATED,
            tag_write_state=WRITE_NOT_WRITTEN,
        )

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            on_scan_complete_pipeline_hook(mock_db, library)

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            library,
            ML_STATE_FIELD,
            ML_NOT_PROCESSED,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestSnapshotExistingFiles:
    """Tests for collecting the pre-scan file snapshot."""

    def test_returns_existing_files_indexed_by_path_and_tagged_flag(self) -> None:
        mock_db = MagicMock()
        library = _library()
        files = [
            HydratedSong(song=_song(path="a.mp3"), metadata={}),
            HydratedSong(song=_song(path="b.mp3"), metadata={}),
        ]

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.list_songs",
                return_value=(files, 2),
            ) as mock_list_songs,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.library_has_tagged_files",
                return_value=True,
            ) as mock_library_has_tagged_files,
        ):
            result = snapshot_existing_files(mock_db, library)

        assert result == ({"a.mp3": files[0], "b.mp3": files[1]}, True)
        mock_list_songs.assert_called_once_with(mock_db, library=library, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, library)

    def test_returns_empty_snapshot_when_library_has_no_files(self) -> None:
        mock_db = MagicMock()
        library = _library()

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.list_songs",
                return_value=([], 0),
            ) as mock_list_songs,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.library_has_tagged_files",
                return_value=False,
            ) as mock_library_has_tagged_files,
        ):
            result = snapshot_existing_files(mock_db, library)

        assert result == ({}, False)
        mock_list_songs.assert_called_once_with(mock_db, library=library, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, library)


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertScannedFiles:
    """Tests for batched scan-time file upserts."""

    def test_returns_batch_ids_without_bootstrapping_edges_when_none_provided(self) -> None:
        mock_db = MagicMock()
        library = _library()
        file_entries = [{"normalized_path": "music/song.mp3"}]
        si_one = _identity("music/song.mp3")

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp._upsert_batch",
                return_value=[si_one],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = upsert_scanned_files(mock_db, library, file_entries)

        assert result == [si_one]
        mock_upsert_batch.assert_called_once_with(mock_db, library, file_entries)
        mock_bootstrap_file_state_edges.assert_not_called()

    def test_bootstraps_edges_with_path_to_id_map_when_metadata_is_provided(self) -> None:
        mock_db = MagicMock()
        library = _library()
        file_entries = [
            {"normalized_path": "music/song-a.mp3", "path": "C:/music/song-a.mp3"},
            {"normalized_path": "music/song-b.mp3", "path": "C:/music/song-b.mp3"},
        ]
        edge_bootstraps = [
            {"normalized_path": "music/song-a.mp3", "type": "ml_tagged"},
            {"normalized_path": "music/song-b.mp3", "type": "ml_tagged"},
        ]

        si_a = _identity("music/song-a.mp3")
        si_b = _identity("music/song-b.mp3")

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp._upsert_batch",
                return_value=[si_a, si_b],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = upsert_scanned_files(mock_db, library, file_entries, edge_bootstraps=edge_bootstraps)

        assert result == [si_a, si_b]
        mock_upsert_batch.assert_called_once_with(mock_db, library, file_entries)
        mock_bootstrap_file_state_edges.assert_called_once_with(
            mock_db,
            edge_bootstraps,
            {
                "music/song-a.mp3": si_a,
                "music/song-b.mp3": si_b,
            },
        )
