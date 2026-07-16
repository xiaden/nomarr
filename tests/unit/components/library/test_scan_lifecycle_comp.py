"""Tests for nomarr.components.library.scan_lifecycle_comp module."""

from __future__ import annotations

from unittest.mock import AsyncMock, call, patch

import pytest

from nomarr.components.library.library_scan_file_ops_comp import (
    bootstrap_file_state_edges,
    cleanup_stale_folders,
    remove_deleted_files,
    save_folder_record,
    snapshot_existing_files,
    upsert_scanned_files,
)
from nomarr.components.library.library_scan_state_comp import (
    ensure_scan_state,
    get_scan_state,
)
from nomarr.components.library.scan_lifecycle_comp import (
    LibraryNotFoundError,
    check_interrupted_scan,
    get_library_scan_histories,
    get_scanning_library_ids,
    is_library_scanning,
    mark_scan_completed,
    mark_scan_started,
    on_scan_complete_pipeline_hook,
    resolve_library_for_scan,
    transition_to_scanning,
    update_scan_progress,
)
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.constants.pipeline_states import (
    CAL_NOT_CALIBRATED,
    CAL_STATE_FIELD,
    ML_IN_PROGRESS,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
    WRITE_NOT_WRITTEN,
    WRITE_STATE_FIELD,
)
from nomarr.helpers.dto.library_dto import LibraryDict


class TestBootstrapFileStateEdges:
    """Tests for bootstrap_file_state_edges."""

    @pytest.mark.unit
    async def test_empty_bootstraps_returns_zero(self) -> None:
        mock_db = AsyncMock()
        result = await bootstrap_file_state_edges(mock_db, [], {})
        assert result == 0

    @pytest.mark.unit
    async def test_ml_tagged_type_creates_edge_via_transition(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_file_docs_in_state.side_effect = lambda state: list(
            [{"_id": f"{'library_files'}/abc"}] if state == STATE_NOT_PROCESSED else []
        )
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/song.mp3": f"{'library_files'}/abc"}
        result = await bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 1
        mock_db.library.remove_file_states.assert_called_once_with([f"{'library_files'}/abc"])
        mock_db.library.add_file_states.assert_called_once_with([f"{'library_files'}/abc"], STATE_PROCESSED)
        mock_db.library.transition_file_states.assert_not_called()

    @pytest.mark.unit
    async def test_unknown_bootstrap_type_is_skipped(self) -> None:
        mock_db = AsyncMock()
        bootstraps = [
            {"normalized_path": "/music/song.mp3", "type": "unknown_type"},
        ]
        file_id_by_path = {"/music/song.mp3": f"{'library_files'}/abc"}
        result = await bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.library.remove_file_states.assert_not_called()
        mock_db.library.add_file_states.assert_not_called()
        mock_db.library.transition_file_states.assert_not_called()

    @pytest.mark.unit
    async def test_file_not_in_file_id_by_path_is_skipped(self) -> None:
        mock_db = AsyncMock()
        bootstraps = [
            {"normalized_path": "/music/missing.mp3", "type": "ml_tagged"},
        ]
        file_id_by_path = {"/music/other.mp3": f"{'library_files'}/xyz"}
        result = await bootstrap_file_state_edges(mock_db, bootstraps, file_id_by_path)
        assert result == 0
        mock_db.library.remove_file_states.assert_not_called()
        mock_db.library.add_file_states.assert_not_called()
        mock_db.library.transition_file_states.assert_not_called()


class TestIsLibraryScanning:
    """Tests for is_library_scanning."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_false_when_get_state_raises_value_error(self) -> None:
        mock_db = AsyncMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = None

        result = await is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")


class TestGetScanningLibraryIds:
    """Tests for get_scanning_library_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_deduplicated_library_dicts(self) -> None:
        mock_db = AsyncMock()

        def _get_library(library_id: str) -> dict | None:
            return {
                "_id": library_id,
                "_key": library_id.split("/", 1)[1],
                "_rev": "rev",
                "name": f"lib-{library_id}",
                "root_path": "/tmp",
                "is_enabled": True,
                "created_at": 0,
                "updated_at": 0,
            }

        mock_db.libraries.get_library.side_effect = _get_library

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.get_libraries_in_axis_state",
            return_value=["libraries/one", "libraries/two", "libraries/one"],
        ) as mock_get_libraries:
            result = await get_scanning_library_ids(mock_db)

        assert isinstance(result, list)
        assert len(result) == 2
        assert {lib._id for lib in result} == {"libraries/one", "libraries/two"}
        mock_get_libraries.assert_called_once_with(mock_db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


class TestGetLibraryScanHistories:
    """Tests for get_library_scan_histories."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_projected_scan_history_for_all_libraries(self) -> None:
        mock_db = AsyncMock()
        lib_one = LibraryDict(
            _id="libraries/one",
            _key="one",
            _rev="_",
            name="Main Library",
            root_path="/tmp",
            is_enabled=True,
            created_at=0,
            updated_at=0,
            scanned_at=123,
            scan_status="complete",
        )
        lib_two = LibraryDict(
            _id="libraries/two",
            _key="two",
            _rev="_",
            name="Lib",
            root_path="/tmp",
            is_enabled=True,
            created_at=0,
            updated_at=0,
            scanned_at=None,
            scan_status="idle",
        )
        libraries = [lib_one, lib_two]

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.list_library_records",
            return_value=libraries,
        ):
            result = await get_library_scan_histories(mock_db)

        assert result == [
            {
                "library_id": "libraries/one",
                "name": "Main Library",
                "scanned_at": 123,
                "scan_status": "complete",
            },
            {
                "library_id": "libraries/two",
                "name": "Lib",
                "scanned_at": None,
                "scan_status": "idle",
            },
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_applies_limit_before_projection(self) -> None:
        mock_db = AsyncMock()
        libraries = [
            LibraryDict(
                _id="libraries/one",
                _key="one",
                _rev="_",
                name="One",
                root_path="/tmp",
                is_enabled=True,
                created_at=0,
                updated_at=0,
                scanned_at=None,
                scan_status="idle",
            ),
            LibraryDict(
                _id="libraries/two",
                _key="two",
                _rev="_",
                name="Two",
                root_path="/tmp",
                is_enabled=True,
                created_at=0,
                updated_at=0,
                scanned_at=None,
                scan_status="idle",
            ),
            LibraryDict(
                _id="libraries/three",
                _key="three",
                _rev="_",
                name="Three",
                root_path="/tmp",
                is_enabled=True,
                created_at=0,
                updated_at=0,
                scanned_at=456,
                scan_status="complete",
            ),
        ]

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.list_library_records",
            return_value=libraries,
        ):
            result = await get_library_scan_histories(mock_db, limit=2)

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
                "scan_status": "idle",
            },
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_true_when_pipeline_state_is_scanning(self) -> None:
        mock_db = AsyncMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = {
            SCAN_STATE_FIELD: SCAN_IN_PROGRESS,
            ML_STATE_FIELD: ML_NOT_PROCESSED,
            CAL_STATE_FIELD: CAL_NOT_CALIBRATED,
            WRITE_STATE_FIELD: WRITE_NOT_WRITTEN,
        }

        result = await is_library_scanning(mock_db, library_id)

        assert result is True
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_false_when_pipeline_state_is_not_scanning(self) -> None:
        mock_db = AsyncMock()
        library_id = "libraries/test"
        mock_db.app.get_pipeline_state.return_value = {
            SCAN_STATE_FIELD: "scanned",
            ML_STATE_FIELD: ML_NOT_PROCESSED,
            CAL_STATE_FIELD: CAL_NOT_CALIBRATED,
            WRITE_STATE_FIELD: WRITE_NOT_WRITTEN,
        }

        result = await is_library_scanning(mock_db, library_id)

        assert result is False
        mock_db.app.get_pipeline_state.assert_called_once_with("libraries/test")


class TestScanStateHelpers:
    """Tests for constructor-backed scan state orchestration helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_ensure_scan_state_inserts_default_doc_and_edge_when_missing(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.get_scan.side_effect = [None, {"_id": "library_scans/test", "library_key": "test"}]

        result = await ensure_scan_state(mock_db, "libraries/test")

        mock_db.library.add_scan.assert_called_once()
        assert mock_db.library.add_scan.call_args.args[0] == "libraries/test"
        inserted_doc = mock_db.library.add_scan.call_args.args[1]
        assert inserted_doc["_key"] == "test"
        assert inserted_doc["library_key"] == "test"
        assert result["library_key"] == "test"

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_get_scan_state_looks_up_scan_doc_by_id_keyword(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.get_scan.return_value = None

        result = await get_scan_state(mock_db, "libraries/test")

        mock_db.library.get_scan.assert_called_once_with("libraries/test")
        mock_db.library.add_scan.assert_not_called()
        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_get_scan_state_repairs_legacy_row_missing_library_key(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.get_scan.side_effect = [
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "status": "idle"},
            {"_id": "library_scans/test", "_key": "test", "library_key": "test", "status": "idle"},
        ]

        result = await get_scan_state(mock_db, "libraries/test")

        mock_db.library.get_scan.assert_any_call("libraries/test")
        mock_db.library.remove_scan.assert_called_once_with("libraries/test")
        repaired_doc = mock_db.library.add_scan.call_args.args[1]
        assert repaired_doc["library_key"] == "test"
        assert result is not None
        assert result["library_key"] == "test"

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_mark_scan_started_delegates_to_database_facade(self) -> None:
        mock_db = AsyncMock()

        await mark_scan_started(mock_db, "libraries/test", "full")

        mock_db.library.add_scan.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_mark_scan_completed_delegates_to_database_facade(self) -> None:
        mock_db = AsyncMock()

        await mark_scan_completed(mock_db, "libraries/test")

        mock_db.library.update_scan.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_update_scan_progress_delegates_to_database_facade(self) -> None:
        mock_db = AsyncMock()

        await update_scan_progress(
            mock_db,
            "libraries/test",
            progress=5,
            total=12,
            scan_error="boom",
        )

        mock_db.library.update_scan.assert_called_once_with(
            "libraries/test",
            {"progress": 5, "total": 12, "scan_error": "boom"},
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_check_interrupted_scan_delegates_to_database_facade(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.get_scan.return_value = {"status": "in_progress", "scan_type": "quick"}

        assert await check_interrupted_scan(mock_db, "libraries/test") == (True, "quick")
        mock_db.library.get_scan.assert_called_once_with("libraries/test")


class TestFolderCacheHelpers:
    """Tests for constructor-backed folder cache persistence helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_save_folder_record_replaces_existing_doc_via_library_intents(self) -> None:
        mock_db = AsyncMock()

        with patch("nomarr.components.library.library_scan_file_ops_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 456
            await save_folder_record(
                mock_db,
                "libraries/test",
                "Rock",
                123,
                7,
                existing_folder_id="library_folders/existing",
            )

        inserted_doc = mock_db.library.add_library_folder.call_args.args[1]
        assert inserted_doc["path"] == "Rock"
        assert inserted_doc["library_key"] == "test"
        assert inserted_doc["mtime"] == 123
        assert inserted_doc["file_count"] == 7
        assert inserted_doc["last_scanned_at"] == 456

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_cleanup_stale_folders_deletes_only_missing_paths(self) -> None:
        mock_db = AsyncMock()

        with patch(
            "nomarr.components.library.library_scan_file_ops_comp.get_cached_folders",
            return_value={
                "Keep": {"_id": "library_folders/a", "path": "Keep"},
                "Drop": {"_id": "library_folders/b", "path": "Drop"},
            },
        ):
            await cleanup_stale_folders(mock_db, "libraries/test", {"Keep"})

        mock_db.library.remove_library_folder.assert_called_once_with("libraries/test", "library_folders/b")


@pytest.mark.unit
@pytest.mark.mocked
class TestRemoveDeletedFiles:
    """Tests for remove_deleted_files."""

    async def test_remove_deleted_files_delegates_cleanup_to_remove_file(self) -> None:
        """remove_deleted_files resolves file ids and delegates deletion to library.remove_file."""
        mock_db = AsyncMock()
        paths = ["/music/a.mp3", "/music/b.mp3", "/music/c.mp3"]
        mock_db.library.find_file_by_path_any_library.side_effect = [
            {"_id": f"{'library_files'}/a"},
            {"_id": f"{'library_files'}/b"},
            None,
        ]

        result = await remove_deleted_files(mock_db, paths)

        assert mock_db.library.remove_file.call_args_list == [
            call(f"{'library_files'}/a"),
            call(f"{'library_files'}/b"),
        ]
        assert result == 2

    async def test_remove_deleted_files_returns_zero_for_empty_list(self) -> None:
        """remove_deleted_files skips lookup and deletion when no file paths are supplied."""
        mock_db = AsyncMock()

        result = await remove_deleted_files(mock_db, [])

        mock_db.library.find_file_by_path_any_library.assert_not_called()
        mock_db.library.remove_file.assert_not_called()
        assert result == 0


@pytest.mark.unit
@pytest.mark.mocked
class TestResolveLibraryForScan:
    """Tests for library lookup before a scan starts."""

    async def test_returns_library_when_lookup_succeeds(self) -> None:
        mock_db = AsyncMock()
        library = {
            "_id": "libraries/1",
            "_key": "1",
            "_rev": "_",
            "name": "Main",
            "root_path": "/tmp",
            "is_enabled": True,
            "created_at": 0,
            "updated_at": 0,
        }
        mock_db.libraries.get_library.return_value = library

        result = await resolve_library_for_scan(mock_db, "libraries/1")

        assert isinstance(result, LibraryDict)
        assert result._id == "libraries/1"
        assert result.name == "Main"
        mock_db.libraries.get_library.assert_called_once_with("libraries/1")

    async def test_raises_library_not_found_when_lookup_returns_none(self) -> None:
        mock_db = AsyncMock()
        mock_db.libraries.get_library.return_value = None

        with pytest.raises(LibraryNotFoundError, match="Library libraries/missing not found"):
            await resolve_library_for_scan(mock_db, "libraries/missing")

        mock_db.libraries.get_library.assert_called_once_with("libraries/missing")


@pytest.mark.unit
@pytest.mark.mocked
class TestTransitionToScanning:
    """Tests for pipeline transition into scanning."""

    async def test_delegates_to_transition_pipeline_axis_with_scanning(self) -> None:
        mock_db = AsyncMock()

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            await transition_to_scanning(mock_db, "libraries/1")

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            "libraries/1",
            SCAN_STATE_FIELD,
            SCAN_IN_PROGRESS,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestOnScanCompletePipelineHook:
    """Tests for post-scan pipeline state transitions."""

    async def test_transitions_ml_axis_when_files_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_library_file_ids.return_value = ["file1", "file2"]

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            await on_scan_complete_pipeline_hook(mock_db, "libraries/1")

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            "libraries/1",
            ML_STATE_FIELD,
            ML_IN_PROGRESS,
        )

    async def test_transitions_ml_axis_when_no_files(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_library_file_ids.return_value = []

        with patch(
            "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis"
        ) as mock_transition_pipeline_axis:
            await on_scan_complete_pipeline_hook(mock_db, "libraries/1")

        mock_transition_pipeline_axis.assert_called_once_with(
            mock_db,
            "libraries/1",
            ML_STATE_FIELD,
            ML_NOT_PROCESSED,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestSnapshotExistingFiles:
    """Tests for collecting the pre-scan file snapshot."""

    async def test_returns_existing_files_indexed_by_path_and_tagged_flag(self) -> None:
        mock_db = AsyncMock()
        files = [
            {"_id": f"{'library_files'}/a", "path": "a.mp3"},
            {"_id": f"{'library_files'}/b", "path": "b.mp3"},
        ]

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.list_library_files",
                return_value=(files, 2),
            ) as mock_list_library_files,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.library_has_tagged_files",
                return_value=True,
            ) as mock_library_has_tagged_files,
        ):
            result = await snapshot_existing_files(mock_db, "libraries/1")

        assert result == ({"a.mp3": files[0], "b.mp3": files[1]}, True)
        mock_list_library_files.assert_called_once_with(mock_db, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, "libraries/1")

    async def test_returns_empty_snapshot_when_library_has_no_files(self) -> None:
        mock_db = AsyncMock()

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.list_library_files",
                return_value=([], 0),
            ) as mock_list_library_files,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.library_has_tagged_files",
                return_value=False,
            ) as mock_library_has_tagged_files,
        ):
            result = await snapshot_existing_files(mock_db, "libraries/1")

        assert result == ({}, False)
        mock_list_library_files.assert_called_once_with(mock_db, limit=1_000_000, offset=0)
        mock_library_has_tagged_files.assert_called_once_with(mock_db, "libraries/1")


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertScannedFiles:
    """Tests for batched scan-time file upserts."""

    async def test_returns_batch_ids_without_bootstrapping_edges_when_none_provided(self) -> None:
        mock_db = AsyncMock()
        file_entries = [{"normalized_path": "music/song.mp3"}]

        with (
            patch(
                "nomarr.components.library.library_scan_file_ops_comp._upsert_batch",
                return_value=[f"{'library_files'}/1"],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = await upsert_scanned_files(mock_db, file_entries)

        assert result == [f"{'library_files'}/1"]
        mock_upsert_batch.assert_called_once_with(mock_db, file_entries)
        mock_bootstrap_file_state_edges.assert_not_called()

    async def test_bootstraps_edges_with_path_to_id_map_when_metadata_is_provided(self) -> None:
        mock_db = AsyncMock()
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
                "nomarr.components.library.library_scan_file_ops_comp._upsert_batch",
                return_value=[f"{'library_files'}/a", f"{'library_files'}/b"],
            ) as mock_upsert_batch,
            patch(
                "nomarr.components.library.library_scan_file_ops_comp.bootstrap_file_state_edges"
            ) as mock_bootstrap_file_state_edges,
        ):
            result = await upsert_scanned_files(mock_db, file_entries, edge_bootstraps=edge_bootstraps)

        assert result == [f"{'library_files'}/a", f"{'library_files'}/b"]
        mock_upsert_batch.assert_called_once_with(mock_db, file_entries)
        mock_bootstrap_file_state_edges.assert_called_once_with(
            mock_db,
            edge_bootstraps,
            {
                "music/song-a.mp3": f"{'library_files'}/a",
                "music/song-b.mp3": f"{'library_files'}/b",
            },
        )
