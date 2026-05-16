"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.scan_lifecycle_comp import (
    LibraryNotFoundError,
    bootstrap_file_state_edges,
    check_interrupted_scan,
    cleanup_stale_folders,
    ensure_scan_state,
    get_library_scan_histories,
    get_scan_state,
    get_scanning_library_ids,
    is_library_scanning,
    mark_scan_completed,
    mark_scan_started,
    on_scan_complete_pipeline_hook,
    remove_deleted_files,
    resolve_library_for_scan,
    save_folder_record,
    snapshot_existing_files,
    transition_to_scanning,
    update_scan_progress,
    upsert_scanned_files,
)
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
    PIPELINE_SCANNING,
)
from nomarr.helpers.time_helper import Milliseconds


class TestBootstrapFileStateEdges:
    """Tests for bootstrap_file_state_edges."""

    @pytest.mark.unit
    def test_empty_bootstraps_returns_zero(self) -> None:
        mock_db = MagicMock()
        result = bootstrap_file_state_edges(mock_db, [], {})
        assert result == 0

    @pytest.mark.unit
    def test_ml_tagged_type_creates_edge_via_transition(self) -> None:
        mock_db = MagicMock()
        mock_db.app.list_file_docs_in_state.side_effect = lambda state: list(
            [{"_id": "library_files/abc"}] if state == STATE_NOT_TAGGED else []
        )
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 1
        mock_db.app.remove_file_states.assert_called_once_with(["library_files/abc"])
        mock_db.app.add_file_states.assert_called_once_with(["library_files/abc"], STATE_TAGGED)
        mock_db.app.transition_file_states.assert_not_called()

    @pytest.mark.unit
    def test_unknown_bootstrap_type_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "unknown_type"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.app.remove_file_states.assert_not_called()
        mock_db.app.add_file_states.assert_not_called()
        mock_db.app.transition_file_states.assert_not_called()

    @pytest.mark.unit
    def test_file_not_in_file_id_by_path_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/missing.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/other.mp3": "library_files/xyz"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.app.remove_file_states.assert_not_called()
        mock_db.app.add_file_states.assert_not_called()
        mock_db.app.transition_file_states.assert_not_called()


class TestIsLibraryScanning:
    """Tests for is_library_scanning."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_get_state_raises_value_error(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = None

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")


class TestGetScanningLibraryIds:
    """Tests for get_scanning_library_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_scanning_state_query_and_returns_set(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.get_libraries_in_pipeline_state",
            return_value=["libraries/one", "libraries/two", "libraries/one"],
        ) as mock_get_libraries:
            result = get_scanning_library_ids(mock_db)

        assert result == {"libraries/one", "libraries/two"}
        assert isinstance(result, set)
        mock_get_libraries.assert_called_once_with(mock_db, PIPELINE_SCANNING)


class TestGetLibraryScanHistories:
    """Tests for get_library_scan_histories."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_scan_history_for_all_libraries(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {
                "_id": "libraries/one",
                "name": "Main Library",
                "scanned_at": 123,
                "ignored": "value",
            },
            {
                "_id": "libraries/two",
                "scanned_at": None,
            },
        ]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._list_library_records",
                return_value=libraries,
            ) as mock_list_library_records,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.get_scan_state",
                side_effect=[{"completed_at": 123}, None],
            ) as mock_get_scan_state,
        ):
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
        mock_list_library_records.assert_called_once_with(mock_db)
        assert mock_get_scan_state.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_limit_before_projection(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/one", "name": "One"},
            {"_id": "libraries/two", "name": "Two"},
            {"_id": "libraries/three", "name": "Three"},
        ]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._list_library_records",
                return_value=libraries,
            ) as mock_list_library_records,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.get_scan_state",
                side_effect=[None, {"error": "boom"}],
            ) as mock_get_scan_state,
        ):
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
                "scan_status": "error",
            },
        ]
        mock_list_library_records.assert_called_once_with(mock_db)
        assert mock_get_scan_state.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_pipeline_state_is_scanning(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = PIPELINE_SCANNING.rsplit("/", maxsplit=1)[-1]

        result = is_library_scanning(mock_db, library_id)

        assert result is True
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_pipeline_state_is_not_scanning(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = "idle"

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")


class TestScanStateHelpers:
    """Tests for constructor-backed scan state orchestration helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_ensure_scan_state_inserts_default_doc_and_edge_when_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_scan.side_effect = [None, {"_id": "library_scans/test", "library_key": "test"}]

        result = ensure_scan_state(mock_db, "libraries/test")

        mock_db.app.add_scan.assert_called_once()
        assert mock_db.app.add_scan.call_args.args[0] == "libraries/test"
        inserted_doc = mock_db.app.add_scan.call_args.args[1]
        assert inserted_doc["_key"] == "test"
        assert inserted_doc["library_key"] == "test"
        assert result["library_key"] == "test"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_looks_up_scan_doc_by_id_keyword(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_scan.return_value = None

        result = get_scan_state(mock_db, "libraries/test")

        mock_db.app.get_scan.assert_called_once_with("libraries/test")
        mock_db.app.add_scan.assert_not_called()
        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_repairs_legacy_row_missing_library_key(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_scan.side_effect = [
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "library_key": "test", "status": "idle"},
        ]

        result = get_scan_state(mock_db, "libraries/test")

        mock_db.app.get_scan.assert_any_call("libraries/test")
        mock_db.app.remove_scan.assert_called_once_with("libraries/test")
        repaired_doc = mock_db.app.add_scan.call_args.args[1]
        assert repaired_doc["library_key"] == "test"
        assert result is not None
        assert result["library_key"] == "test"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mark_scan_started_updates_started_at_and_scan_type(self) -> None:
        mock_db = MagicMock()

        with (
            patch("nomarr.components.library.scan_lifecycle_comp.now_ms", return_value=Milliseconds(1234)),
            patch("nomarr.components.library.scan_lifecycle_comp.update_scan_state") as mock_update_scan_state,
        ):
            mark_scan_started(mock_db, "libraries/test", "full")

        mock_update_scan_state.assert_called_once_with(
            mock_db,
            "libraries/test",
            started_at=1234,
            scan_type="full",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mark_scan_completed_clears_inflight_fields(self) -> None:
        mock_db = MagicMock()

        with (
            patch("nomarr.components.library.scan_lifecycle_comp.now_ms", return_value=Milliseconds(5678)),
            patch("nomarr.components.library.scan_lifecycle_comp.update_scan_state") as mock_update_scan_state,
        ):
            mark_scan_completed(mock_db, "libraries/test")

        mock_update_scan_state.assert_called_once_with(
            mock_db,
            "libraries/test",
            completed_at=5678,
            started_at=None,
            scan_type=None,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_scan_progress_maps_progress_fields(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.scan_lifecycle_comp.update_scan_state") as mock_update_scan_state:
            update_scan_progress(
                mock_db,
                "libraries/test",
                progress=5,
                total=12,
                scan_error="boom",
            )

        mock_update_scan_state.assert_called_once_with(
            mock_db,
            "libraries/test",
            files_processed=5,
            files_total=12,
            error="boom",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_check_interrupted_scan_uses_scan_doc_timestamps(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_scan.return_value = {
            "_id": "library_scans/test",
            "_key": "test",
            "library_key": "test",
            "started_at": 200,
            "completed_at": 100,
            "scan_type": "quick",
        }

        assert check_interrupted_scan(mock_db, "libraries/test") == (True, "quick")


class TestFolderCacheHelpers:
    """Tests for constructor-backed folder cache persistence helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_save_folder_record_replaces_existing_doc_via_library_intents(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.scan_lifecycle_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 456
            save_folder_record(
                mock_db,
                "libraries/test",
                "Rock",
                123,
                7,
                existing_folder_id="library_folders/existing",
            )

        inserted_doc = mock_db.library.add_library_folder.call_args.args[1]
        mock_db.library.remove_library_folder.assert_called_once_with(
            "libraries/test",
            "library_folders/existing",
        )
        assert inserted_doc["path"] == "Rock"
        assert inserted_doc["library_key"] == "test"
        assert inserted_doc["mtime"] == 123
        assert inserted_doc["file_count"] == 7
        assert inserted_doc["last_scanned_at"] == 456

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cleanup_stale_folders_deletes_only_missing_paths(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.get_cached_folders",
            return_value={
                "Keep": {"_id": "library_folders/a", "path": "Keep"},
                "Drop": {"_id": "library_folders/b", "path": "Drop"},
            },
        ):
            cleanup_stale_folders(mock_db, "libraries/test", {"Keep"})

        mock_db.library.remove_library_folder.assert_called_once_with("libraries/test", "library_folders/b")


@pytest.mark.unit
@pytest.mark.mocked
class TestRemoveDeletedFiles:
    """Tests for remove_deleted_files."""

    def test_remove_deleted_files_delegates_cleanup_to_remove_file(self) -> None:
        """remove_deleted_files resolves file ids and delegates deletion to library.remove_file."""
        mock_db = MagicMock()
        paths = ["/music/a.mp3", "/music/b.mp3", "/music/c.mp3"]
        mock_db.library.find_file_by_path_any_library.side_effect = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
            None,
        ]

        result = remove_deleted_files(mock_db, paths)

        assert mock_db.library.remove_file.call_args_list == [
            call("library_files/a"),
            call("library_files/b"),
        ]
        assert result == 2

    def test_remove_deleted_files_returns_zero_for_empty_list(self) -> None:
        """remove_deleted_files skips lookup and deletion when no file paths are supplied."""
        mock_db = MagicMock()

        result = remove_deleted_files(mock_db, [])

        mock_db.library.find_file_by_path_any_library.assert_not_called()
        mock_db.library.remove_file.assert_not_called()
        assert result == 0


@pytest.mark.unit
@pytest.mark.mocked
class TestResolveLibraryForScan:
    """Tests for library lookup before a scan starts."""

    def test_returns_library_when_lookup_succeeds(self) -> None:
        mock_db = MagicMock()
        library = {"_id": "libraries/1", "name": "Main"}
        mock_db.library.get_library.return_value = library

        result = resolve_library_for_scan(mock_db, "libraries/1")

        assert result == library
        mock_db.library.get_library.assert_called_once_with("libraries/1")

    def test_raises_library_not_found_when_lookup_returns_none(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library.return_value = None

        with pytest.raises(LibraryNotFoundError, match="Library libraries/missing not found"):
            resolve_library_for_scan(mock_db, "libraries/missing")

        mock_db.library.get_library.assert_called_once_with("libraries/missing")


@pytest.mark.unit
@pytest.mark.mocked
class TestTransitionToScanning:
    """Tests for pipeline transition into scanning."""

    def test_delegates_to_transition_pipeline_state_with_scanning(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_state"
        ) as mock_transition_pipeline_state:
            transition_to_scanning(mock_db, "libraries/1")

        mock_transition_pipeline_state.assert_called_once_with(
            mock_db,
            "libraries/1",
            PIPELINE_SCANNING,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestOnScanCompletePipelineHook:
    """Tests for post-scan pipeline state transitions."""

    def test_transitions_to_ml_running_when_library_has_files(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp.count_library_files",
                return_value=5,
            ) as mock_count_library_files,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_state"
            ) as mock_transition_pipeline_state,
        ):
            on_scan_complete_pipeline_hook(mock_db, "libraries/1")

        mock_count_library_files.assert_called_once_with(mock_db, "libraries/1")
        mock_transition_pipeline_state.assert_called_once_with(
            mock_db,
            "libraries/1",
            PIPELINE_ML_RUNNING,
        )

    def test_transitions_to_idle_when_library_has_no_files(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp.count_library_files",
                return_value=0,
            ) as mock_count_library_files,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_state"
            ) as mock_transition_pipeline_state,
        ):
            on_scan_complete_pipeline_hook(mock_db, "libraries/1")

        mock_count_library_files.assert_called_once_with(mock_db, "libraries/1")
        mock_transition_pipeline_state.assert_called_once_with(
            mock_db,
            "libraries/1",
            PIPELINE_IDLE,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestSnapshotExistingFiles:
    """Tests for collecting the pre-scan file snapshot."""

    def test_returns_existing_files_indexed_by_path_and_tagged_flag(self) -> None:
        mock_db = MagicMock()
        files = [
            {"_id": "library_files/a", "path": "a.mp3"},
            {"_id": "library_files/b", "path": "b.mp3"},
        ]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp.list_library_files",
                return_value=(files, 2),
            ) as mock_list_library_files,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.library_has_tagged_files",
                return_value=True,
            ) as mock_library_has_tagged_files,
        ):
            result = snapshot_existing_files(mock_db, "libraries/1")

        assert result == ({"a.mp3": files[0], "b.mp3": files[1]}, True)
        mock_list_library_files.assert_called_once_with(mock_db, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, "libraries/1")

    def test_returns_empty_snapshot_when_library_has_no_files(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp.list_library_files",
                return_value=([], 0),
            ) as mock_list_library_files,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.library_has_tagged_files",
                return_value=False,
            ) as mock_library_has_tagged_files,
        ):
            result = snapshot_existing_files(mock_db, "libraries/1")

        assert result == ({}, False)
        mock_list_library_files.assert_called_once_with(mock_db, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, "libraries/1")


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertScannedFiles:
    """Tests for batched scan-time file upserts."""

    def test_returns_batch_ids_without_bootstrapping_edges_when_none_provided(self) -> None:
        mock_db = MagicMock()
        file_entries = [{"normalized_path": "music/song.mp3"}]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._upsert_batch",
                return_value=["library_files/1"],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = upsert_scanned_files(mock_db, file_entries)

        assert result == ["library_files/1"]
        mock_upsert_batch.assert_called_once_with(mock_db, file_entries)
        mock_bootstrap_file_state_edges.assert_not_called()

    def test_bootstraps_edges_with_path_to_id_map_when_metadata_is_provided(self) -> None:
        mock_db = MagicMock()
        file_entries = [
            {"normalized_path": "music/song-a.mp3", "path": "C:/music/song-a.mp3"},
            {"normalized_path": "music/song-b.mp3", "path": "C:/music/song-b.mp3"},
        ]
        edge_bootstraps = [
            {"normalized_path": "music/song-a.mp3", "type": "ml_tagged"},
            {"normalized_path": "music/song-b.mp3", "type": "ml_tagged"},
        ]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._upsert_batch",
                return_value=["library_files/a", "library_files/b"],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.scan_lifecycle_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = upsert_scanned_files(mock_db, file_entries, edge_bootstraps=edge_bootstraps)

        assert result == ["library_files/a", "library_files/b"]
        mock_upsert_batch.assert_called_once_with(mock_db, file_entries)
        mock_bootstrap_file_state_edges.assert_called_once_with(
            mock_db,
            edge_bootstraps,
            {
                "music/song-a.mp3": "library_files/a",
                "music/song-b.mp3": "library_files/b",
            },
        )
