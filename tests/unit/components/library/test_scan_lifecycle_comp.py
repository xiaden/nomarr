"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.scan_lifecycle_comp import (
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
    remove_deleted_files,
    save_folder_record,
    update_scan_progress,
)
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED
from nomarr.helpers.constants.pipeline_states import PIPELINE_SCANNING
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
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 1
        mock_db.file_states.transition.assert_called_once_with(["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED)

    @pytest.mark.unit
    def test_unknown_bootstrap_type_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "unknown_type"},
        ]
        file_id_by_path = {"/music/song.mp3": "library_files/abc"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.file_states.transition.assert_not_called()

    @pytest.mark.unit
    def test_file_not_in_file_id_by_path_is_skipped(self) -> None:
        mock_db = MagicMock()
        bootstraps = [
            {"normalized_path": "/music/missing.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/other.mp3": "library_files/xyz"}
        result = bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.file_states.transition.assert_not_called()


class TestIsLibraryScanning:
    """Tests for is_library_scanning."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_get_state_raises_value_error(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.library_pipeline_states.get.return_value = None

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.library_pipeline_states.get.assert_called_once_with(library_key="test")


class TestGetScanningLibraryIds:
    """Tests for get_scanning_library_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_scanning_state_query_and_returns_set(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.count.return_value = 3
        mock_db.library_pipeline_states.get.return_value = [
            {"library_key": "one", "pipeline_state": PIPELINE_SCANNING},
            {"library_key": "two", "pipeline_state": PIPELINE_SCANNING},
            {"library_key": "one", "pipeline_state": PIPELINE_SCANNING},
        ]

        result = get_scanning_library_ids(mock_db)

        assert result == {"libraries/one", "libraries/two"}
        assert isinstance(result, set)
        mock_db.library_pipeline_states.get.assert_called_once_with(
            pipeline_state=PIPELINE_SCANNING,
            limit=3,
        )


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
        PIPELINE_SCANNING.rsplit("/", maxsplit=1)[-1]
        mock_db.library_pipeline_states.get.return_value = {
            "library_key": "test",
            "pipeline_state": PIPELINE_SCANNING,
        }

        result = is_library_scanning(mock_db, library_id)

        assert result is True
        mock_db.library_pipeline_states.get.assert_called_once_with(library_key="test")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_pipeline_state_is_not_scanning(self) -> None:
        mock_db = MagicMock()
        library_id = "libraries/test"
        mock_db.library_pipeline_states.get.return_value = {
            "library_key": "test",
            "pipeline_state": "library_pipeline_states/idle",
        }

        result = is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.library_pipeline_states.get.assert_called_once_with(library_key="test")


class TestScanStateHelpers:
    """Tests for constructor-backed scan state orchestration helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_ensure_scan_state_inserts_default_doc_and_edge_when_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.library_scans.get.side_effect = [None, {"_id": "library_scans/test", "library_key": "test"}]

        result = ensure_scan_state(mock_db, "libraries/test")

        mock_db.library_scans.insert.assert_called_once()
        inserted_doc = mock_db.library_scans.insert.call_args.args[0][0]
        assert inserted_doc["_key"] == "test"
        assert inserted_doc["library_key"] == "test"
        mock_db.library_has_scan.upsert.assert_called_once_with(
            _from="libraries/test",
            _to="library_scans/test",
            fields={},
        )
        assert result["library_key"] == "test"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_looks_up_scan_doc_by_id_keyword(self) -> None:
        mock_db = MagicMock()
        mock_db.library_scans.get.return_value = None

        result = get_scan_state(mock_db, "libraries/test")

        mock_db.library_scans.get.assert_called_once_with(_id="library_scans/test")
        mock_db.library_has_scan.upsert.assert_not_called()
        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_state_repairs_legacy_row_missing_library_key(self) -> None:
        mock_db = MagicMock()
        mock_db.library_scans.get.side_effect = [
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "library_key": "test", "status": "idle"},
        ]

        result = get_scan_state(mock_db, "libraries/test")

        mock_db.library_scans.get.assert_any_call(_id="library_scans/test")
        mock_db.library_scans.delete.assert_called_once_with(_id="library_scans/test")
        repaired_doc = mock_db.library_scans.insert.call_args.args[0][0]
        assert repaired_doc["library_key"] == "test"
        mock_db.library_has_scan.upsert.assert_called_once_with(
            _from="libraries/test",
            _to="library_scans/test",
            fields={},
        )
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
        mock_db.library_scans.get.return_value = {
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
    def test_save_folder_record_replaces_existing_doc_and_recreates_edge(self) -> None:
        mock_db = MagicMock()
        mock_db.library_folders.get.return_value = {"_id": "library_folders/existing"}

        save_folder_record(mock_db, "libraries/test", "Rock", 123, 7)

        inserted_doc = mock_db.library_folders.insert.call_args.args[0][0]
        inserted_folder_id = f"library_folders/{inserted_doc['_key']}"
        mock_db.library_contains_folder.delete.assert_called_once_with(_to=inserted_folder_id)
        mock_db.library_folders.delete.assert_called_once_with(_id=inserted_folder_id)
        assert inserted_doc["path"] == "Rock"
        assert inserted_doc["library_key"] == "test"
        assert inserted_doc["mtime"] == 123
        assert inserted_doc["file_count"] == 7
        mock_db.library_contains_folder.upsert.assert_called_once_with(
            _from="libraries/test",
            _to=inserted_folder_id,
            fields={},
        )

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

        mock_db.library_contains_folder.delete.assert_called_once_with(_to="library_folders/b")
        mock_db.library_folders.delete.assert_called_once_with(_id="library_folders/b")


@pytest.mark.unit
@pytest.mark.mocked
class TestRemoveDeletedFiles:
    """Tests for remove_deleted_files."""

    def test_remove_deleted_files_deletes_output_streams_before_bulk_delete(self) -> None:
        """remove_deleted_files cleans canonical streams for matched file ids before deletion."""
        mock_db = MagicMock()
        paths = ["/music/a.mp3", "/music/b.mp3", "/music/c.mp3"]
        mock_db.library_files.get.side_effect = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
            None,
        ]

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._delete_output_streams_for_files"
            ) as delete_streams_mock,
            patch(
                "nomarr.components.library.library_file_mutation_comp.bulk_delete_files",
                return_value=2,
            ) as bulk_delete_mock,
        ):
            result = remove_deleted_files(mock_db, paths)

        delete_streams_mock.assert_called_once_with(mock_db, ["library_files/a", "library_files/b"])
        bulk_delete_mock.assert_called_once_with(mock_db, paths)
        assert result == 2

    def test_remove_deleted_files_returns_zero_for_empty_list(self) -> None:
        """remove_deleted_files skips stream cleanup when no file paths are supplied."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.scan_lifecycle_comp._delete_output_streams_for_files"
            ) as delete_streams_mock,
            patch(
                "nomarr.components.library.library_file_mutation_comp.bulk_delete_files",
                return_value=0,
            ) as bulk_delete_mock,
        ):
            result = remove_deleted_files(mock_db, [])

        delete_streams_mock.assert_not_called()
        bulk_delete_mock.assert_called_once_with(mock_db, [])
        assert result == 0
