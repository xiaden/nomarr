"""Tests for constructor-backed library record helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nomarr.components.library.library_id_comp import library_key_from_ref, normalize_library_id
from nomarr.components.library.library_records_comp import (
    create_library_record,
    find_library_containing_path,
    find_ml_complete_libraries,
    get_library_by_name,
    get_library_record,
    list_all_library_keys,
    list_library_records,
    list_watchable_library_records,
    update_library_config_fields,
    update_library_record,
)
from nomarr.helpers.constants.pipeline_states import ML_IN_PROGRESS
from nomarr.helpers.dto.library_dto import LibraryDict


class TestListAllLibraryKeys:
    """Tests for ``list_all_library_keys()``."""

    @pytest.mark.unit
    async def test_returns_list_of_keys(self) -> None:
        """Returns library document keys from the constructor namespace."""
        mock_db = AsyncMock()
        mock_db.library.list_library_keys.return_value = ["lib1", "lib2"]

        result = await list_all_library_keys(mock_db)

        assert result == ["lib1", "lib2"]
        mock_db.library.list_library_keys.assert_called_once_with()

    @pytest.mark.unit
    async def test_returns_empty_list_when_no_libraries(self) -> None:
        """Returns an empty list when no libraries exist."""
        mock_db = AsyncMock()
        mock_db.library.list_library_keys.return_value = []

        result = await list_all_library_keys(mock_db)

        assert result == []
        mock_db.library.list_library_keys.assert_called_once_with()


class TestNormalizeLibraryId:
    """Tests for ``normalize_library_id()``."""

    @pytest.mark.unit
    def test_returns_full_id_unchanged(self) -> None:
        assert normalize_library_id("libraries/main") == "libraries/main"

    @pytest.mark.unit
    def test_prefixes_bare_key(self) -> None:
        assert normalize_library_id("main") == "libraries/main"


class TestLibraryKeyFromRef:
    """Tests for ``library_key_from_ref()``."""

    @pytest.mark.unit
    def test_extracts_key_from_full_id(self) -> None:
        assert library_key_from_ref("libraries/main") == "main"

    @pytest.mark.unit
    def test_returns_bare_key_unchanged(self) -> None:
        assert library_key_from_ref("main") == "main"


class TestCreateLibraryRecord:
    """Tests for ``create_library_record()``."""

    @pytest.mark.unit
    async def test_inserts_constructor_record_with_defaults(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.add_library.return_value = "libraries/1"

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=123456789)
            result = await create_library_record(
                mock_db,
                name="Main",
                root_path="D:/Music",
            )

        assert result == "libraries/1"
        mock_db.library.add_library.assert_called_once_with(
            {
                "name": "Main",
                "root_path": "D:/Music",
                "is_enabled": True,
                "watch_mode": "off",
                "file_write_mode": "full",
                "library_auto_write": False,
                "created_at": 123456789,
                "updated_at": 123456789,
            }
        )


class TestGetLibraryRecord:
    """Tests for ``get_library_record()``."""

    @pytest.mark.unit
    async def test_gets_full_id_and_merges_scan_by_default(self) -> None:
        mock_db = AsyncMock()
        library_doc = {"_id": "libraries/1", "name": "Main"}
        merged_doc = {**library_doc, "scan_status": "idle"}
        mock_db.library.get_library.return_value = library_doc

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            return_value=merged_doc,
        ) as merge_scan:
            result = await get_library_record(mock_db, "libraries/1")

        assert result == merged_doc
        mock_db.library.get_library.assert_called_once_with("libraries/1")
        merge_scan.assert_called_once_with(mock_db, library_doc)

    @pytest.mark.unit
    async def test_gets_by_key_without_merge_when_scan_disabled(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.get_library.return_value = {"_id": "libraries/2", "name": "Alt"}

        result = await get_library_record(mock_db, "2", include_scan=False)

        assert result == {"_id": "libraries/2", "name": "Alt"}
        mock_db.library.get_library.assert_called_once_with("libraries/2")


class TestGetLibraryByName:
    """Tests for ``get_library_by_name()``."""

    @pytest.mark.unit
    async def test_merges_scan_state_when_requested(self) -> None:
        mock_db = AsyncMock()
        library_doc = {"_id": "libraries/1", "name": "Main"}
        merged_doc = {**library_doc, "scan_status": "running"}
        mock_db.library.get_library_by_name.return_value = library_doc

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            return_value=merged_doc,
        ) as merge_scan:
            result = await get_library_by_name(mock_db, "Main", include_scan=True)

        assert result == merged_doc
        mock_db.library.get_library_by_name.assert_called_once_with("Main")
        merge_scan.assert_called_once_with(mock_db, library_doc)


class TestListLibraryRecords:
    """Tests for ``list_library_records()``."""

    @staticmethod
    def _make_lib(**overrides: Any) -> dict[str, Any]:
        return {
            "_id": "libraries/test",
            "_key": "test",
            "_rev": "rev",
            "name": "Test Library",
            "root_path": "/tmp",
            "is_enabled": True,
            "created_at": 0,
            "updated_at": 0,
            **overrides,
        }

    @pytest.mark.unit
    async def test_returns_library_docs_from_sub_facade_without_manual_sorting(self) -> None:
        mock_db = AsyncMock()
        docs = [self._make_lib(_id="libraries/2"), self._make_lib(_id="libraries/1")]
        mock_db.library.list_libraries.return_value = docs

        result = await list_library_records(mock_db, include_scan=False)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]._id == "libraries/2"
        assert result[1]._id == "libraries/1"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=False)

    @pytest.mark.unit
    async def test_merges_scan_state_for_enabled_only_records(self) -> None:
        mock_db = AsyncMock()
        enabled_docs = [self._make_lib(_id="libraries/1")]
        merged_doc = {**self._make_lib(_id="libraries/1"), "scan_status": "idle"}
        mock_db.library.list_libraries.return_value = enabled_docs

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            return_value=merged_doc,
        ) as merge_scan:
            result = await list_library_records(mock_db, enabled_only=True)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]._id == "libraries/1"
        assert result[0].scan_status == "idle"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=True)
        merge_scan.assert_called_once_with(mock_db, enabled_docs[0])


class TestListWatchableLibraryRecords:
    """Tests for ``list_watchable_library_records()``."""

    @pytest.mark.unit
    async def test_filters_off_modes_and_projects_watch_fields(self) -> None:
        mock_db = AsyncMock()
        lib1 = self._make_watchable_lib("libraries/1", "D:/Music", "poll")
        lib2 = self._make_watchable_lib("libraries/2", "D:/Audiobooks", "off")
        lib3 = self._make_watchable_lib("libraries/3", "D:/Podcasts", None)

        with patch(
            "nomarr.components.library.library_records_comp.list_library_records",
            return_value=[lib1, lib2, lib3],
        ) as list_records:
            result = await list_watchable_library_records(mock_db)

        assert len(result) == 1
        assert result[0]._id == "libraries/1"
        assert result[0].root_path == "D:/Music"
        assert result[0].watch_mode == "poll"
        list_records.assert_called_once_with(mock_db, enabled_only=True, include_scan=False)

    @staticmethod
    def _make_watchable_lib(_id: str, root_path: str, watch_mode: str | None) -> LibraryDict:
        return LibraryDict(
            _id=_id,
            _key="_",
            _rev="_",
            name="x",
            root_path=root_path,
            is_enabled=True,
            created_at=0,
            updated_at=0,
            watch_mode=watch_mode or "off",
        )


class TestUpdateLibraryRecord:
    """Tests for ``update_library_record()``."""

    @pytest.mark.unit
    async def test_updates_normalized_library_id_with_non_none_fields(self) -> None:
        mock_db = AsyncMock()

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=222333444)
            await update_library_record(
                mock_db,
                "main",
                name="Renamed",
                watch_mode="poll",
                description=None,
            )

        mock_db.library.update_library.assert_called_once_with(
            "libraries/main",
            {
                "updated_at": 222333444,
                "name": "Renamed",
                "watch_mode": "poll",
            },
        )


class TestUpdateLibraryConfigFields:
    """Tests for ``update_library_config_fields()``."""

    @pytest.mark.unit
    async def test_merges_set_and_unset_fields_before_delegating(self) -> None:
        mock_db = AsyncMock()

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            await update_library_config_fields(
                mock_db,
                "libraries/1",
                set_fields={"watch_mode": "event"},
                unset_fields=["custom_root", "scan_error"],
            )

        update_record.assert_called_once_with(
            mock_db,
            "libraries/1",
            watch_mode="event",
            custom_root=None,
            scan_error=None,
        )

    @pytest.mark.unit
    async def test_returns_early_when_no_fields_provided(self) -> None:
        mock_db = AsyncMock()

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            await update_library_config_fields(mock_db, "libraries/1")

        update_record.assert_not_called()


class TestFindLibraryContainingPath:
    """Tests for ``find_library_containing_path()``."""

    @staticmethod
    def _make_lib_dto(_id: str, root_path: str) -> LibraryDict:
        return LibraryDict(
            _id=_id,
            _key=_id.split("/", 1)[1],
            _rev="_",
            name=_id,
            root_path=root_path,
            is_enabled=True,
            created_at=0,
            updated_at=0,
        )

    @pytest.mark.unit
    async def test_returns_most_specific_matching_library(self) -> None:
        mock_db = AsyncMock()
        libraries = [
            self._make_lib_dto("libraries/root", "D:/Music"),
            self._make_lib_dto("libraries/nested", "D:/Music/Rock"),
        ]

        with patch(
            "nomarr.components.library.library_records_comp.list_library_records",
            return_value=libraries,
        ) as list_records:
            result = await find_library_containing_path(mock_db, "D:/Music/Rock/song.flac")

        assert result is not None
        assert result._id == "libraries/nested"
        assert result.root_path == "D:/Music/Rock"
        list_records.assert_called_once_with(mock_db, enabled_only=False, include_scan=False)


class TestFindMlCompleteLibraries:
    """Tests for ``find_ml_complete_libraries()``."""

    @pytest.mark.unit
    async def test_returns_empty_list_when_no_state_docs(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_libraries.return_value = []

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={},
            ) as mock_get_library_counts,
            patch("nomarr.components.library.library_records_comp.count_untagged_files") as mock_count_untagged_files,
        ):
            result = await find_ml_complete_libraries(mock_db, min_files=10)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.app.get_pipeline_state.assert_not_called()
        mock_get_library_counts.assert_called_once_with(mock_db)
        mock_count_untagged_files.assert_not_called()

    @pytest.mark.unit
    async def test_excludes_library_with_untagged_files(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_libraries.return_value = [{"_key": "42"}]
        mock_db.library.get_pipeline_state.return_value = {
            "scan_state": "scanned",
            "ml_state": ML_IN_PROGRESS,
            "calibration_state": "not_calibrated",
            "tag_write_state": "not_written",
        }

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={"libraries/42": {"file_count": 12}},
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                return_value=5,
            ) as mock_count_untagged_files,
        ):
            result = await find_ml_complete_libraries(mock_db, min_files=1)

        assert result == []
        mock_count_untagged_files.assert_called_once_with(mock_db, "libraries/42")

    @pytest.mark.unit
    async def test_includes_fully_tagged_library(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_libraries.return_value = [{"_key": "42"}]
        mock_db.library.get_pipeline_state.return_value = {
            "scan_state": "scanned",
            "ml_state": ML_IN_PROGRESS,
            "calibration_state": "not_calibrated",
            "tag_write_state": "not_written",
        }

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={"libraries/42": {"file_count": 12}},
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                return_value=0,
            ) as mock_count_untagged_files,
        ):
            result = await find_ml_complete_libraries(mock_db, min_files=99)

        assert result == [{"library_id": "libraries/42", "tagged_count": 12}]
        mock_count_untagged_files.assert_called_once_with(mock_db, "libraries/42")

    @pytest.mark.unit
    async def test_returns_only_fully_tagged_libraries_when_state_docs_are_mixed(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.list_libraries.return_value = [
            {"_key": "7"},
            {"_key": "42"},
        ]
        mock_db.library.get_pipeline_state.side_effect = [
            {
                "scan_state": "scanned",
                "ml_state": ML_IN_PROGRESS,
                "calibration_state": "not_calibrated",
                "tag_write_state": "not_written",
            },
            {
                "scan_state": "scanned",
                "ml_state": ML_IN_PROGRESS,
                "calibration_state": "not_calibrated",
                "tag_write_state": "not_written",
            },
        ]

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={
                    "libraries/7": {"file_count": 3},
                    "libraries/42": {"file_count": 12},
                },
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                side_effect=[4, 0],
            ) as mock_count_untagged_files,
        ):
            result = await find_ml_complete_libraries(mock_db, min_files=2)

        assert result == [{"library_id": "libraries/42", "tagged_count": 12}]
        assert mock_count_untagged_files.call_args_list == [
            ((mock_db, "libraries/7"),),
            ((mock_db, "libraries/42"),),
        ]
