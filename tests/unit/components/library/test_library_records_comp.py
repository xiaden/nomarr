"""Tests for constructor-backed library record helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_records_comp import (
    create_library_record,
    find_library_containing_path,
    find_ml_complete_libraries,
    get_library_by_name,
    get_library_record,
    list_all_libraries,
    list_library_records,
    list_watchable_library_records,
    update_library_config_fields,
    update_library_record,
)
from nomarr.helpers.constants.pipeline_states import ML_IN_PROGRESS
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryPipelineState, LibraryUpdate


class TestListAllLibraries:
    """Tests for ``list_all_libraries()``."""

    @pytest.mark.unit
    def test_returns_list_of_libraries(self) -> None:
        """Returns domain library values from the constructor namespace."""
        mock_db = MagicMock()
        libs = [
            Library(name="lib1", root_path="/music/1"),
            Library(name="lib2", root_path="/music/2"),
        ]
        mock_db.library.list_libraries.return_value = libs

        result = list_all_libraries(mock_db)

        assert result == libs
        mock_db.library.list_libraries.assert_called_once_with()

    @pytest.mark.unit
    def test_returns_empty_list_when_no_libraries(self) -> None:
        """Returns an empty list when no libraries exist."""
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = []

        result = list_all_libraries(mock_db)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()


class TestCreateLibraryRecord:
    """Tests for ``create_library_record()``."""

    @pytest.mark.unit
    def test_inserts_constructor_record_with_defaults(self) -> None:
        mock_db = MagicMock()
        expected = Library(name="Main", root_path="D:/Music")
        mock_db.library.create_library.return_value = expected

        result = create_library_record(
            mock_db,
            name="Main",
            root_path="D:/Music",
        )

        assert result == expected
        mock_db.library.create_library.assert_called_once_with(expected)


class TestGetLibraryRecord:
    """Tests for ``get_library_record()``."""

    @pytest.mark.unit
    def test_gets_library_by_natural_identity(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")
        mock_db.library.get_library.return_value = library

        result = get_library_record(mock_db, library)

        assert result == library
        mock_db.library.get_library.assert_called_once_with(library)

    @pytest.mark.unit
    def test_include_scan_flag_is_stable_for_signature(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Alt", root_path="/alt")
        mock_db.library.get_library.return_value = library

        result = get_library_record(mock_db, library, include_scan=False)

        assert result == library
        mock_db.library.get_library.assert_called_once_with(library)


class TestGetLibraryByName:
    """Tests for ``get_library_by_name()``."""

    @pytest.mark.unit
    def test_gets_library_by_natural_name(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")
        mock_db.library.get_library_by_name.return_value = library

        result = get_library_by_name(mock_db, "Main", include_scan=True)

        assert result == library
        mock_db.library.get_library_by_name.assert_called_once_with("Main")


class TestListLibraryRecords:
    """Tests for ``list_library_records()``."""

    @staticmethod
    def _make_lib(**overrides: Any) -> Library:
        base: dict[str, Any] = {
            "name": "Test Library",
            "root_path": "/tmp",
            "is_enabled": True,
            "watch_mode": "off",
            "file_write_mode": "full",
            "library_auto_write": False,
            "created_at": 0,
            "updated_at": 0,
        }
        base.update(overrides)
        return Library(**base)

    @pytest.mark.unit
    def test_returns_library_docs_from_sub_facade_without_manual_sorting(self) -> None:
        mock_db = MagicMock()
        docs = [self._make_lib(name="two", root_path="/b"), self._make_lib(name="one", root_path="/a")]
        mock_db.library.list_libraries.return_value = docs

        result = list_library_records(mock_db, include_scan=False)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].name == "two"
        assert result[1].name == "one"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=False)

    @pytest.mark.unit
    def test_maps_repository_columns_to_library_intent_fields(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = [
            self._make_lib(name="Test Library", root_path="/tmp", watch_mode="event", library_auto_write=True)
        ]

        result = list_library_records(mock_db, include_scan=False)

        assert result[0].root_path == "/tmp"
        assert result[0].is_enabled is True
        assert result[0].watch_mode == "event"
        assert result[0].library_auto_write is True

    @pytest.mark.unit
    def test_merges_scan_state_for_enabled_only_records(self) -> None:
        mock_db = MagicMock()
        enabled_docs = [self._make_lib(name="lib1", root_path="/m")]
        mock_db.library.list_libraries.return_value = enabled_docs

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_scan_state",
                return_value=None,
            ),
            patch(
                "nomarr.components.library.library_records_comp.get_pipeline_state",
                return_value=LibraryPipelineState(scan_state="scanned", ml_state=ML_IN_PROGRESS),
            ),
            patch.object(mock_db.library, "get_latest_successful_scan", return_value=None),
        ):
            result = list_library_records(mock_db, enabled_only=True)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "lib1"
        assert result[0].scan_status == "idle"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=True)


class TestListWatchableLibraryRecords:
    """Tests for ``list_watchable_library_records()``."""

    @pytest.mark.unit
    def test_filters_off_modes_and_projects_watch_fields(self) -> None:
        mock_db = MagicMock()
        lib1 = Library(name="One", root_path="D:/Music", watch_mode="poll")
        lib2 = Library(name="Two", root_path="D:/Audiobooks", watch_mode="off")
        lib3 = Library(name="Three", root_path="D:/Podcasts", watch_mode="off")
        mock_db.library.list_libraries.return_value = [lib1, lib2, lib3]

        result = list_watchable_library_records(mock_db)

        assert len(result) == 1
        assert result[0].name == "One"
        assert result[0].root_path == "D:/Music"
        assert result[0].watch_mode == "poll"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=True)


class TestUpdateLibraryRecord:
    """Tests for ``update_library_record()``."""

    @pytest.mark.unit
    def test_updates_normalized_library_id_with_non_none_fields(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=222333444)
            update_library_record(
                mock_db,
                library,
                name="Renamed",
                watch_mode="poll",
                description=None,
            )

        mock_db.library.update_library.assert_called_once_with(
            library,
            LibraryUpdate(
                name="Renamed",
                watch_mode="poll",
                updated_at=222333444,
            ),
        )

    @pytest.mark.unit
    def test_persists_file_write_mode(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=222333444)
            update_library_record(mock_db, library, file_write_mode="minimal")

        mock_db.library.update_library.assert_called_once_with(
            library,
            LibraryUpdate(file_write_mode="minimal", updated_at=222333444),
        )


class TestUpdateLibraryConfigFields:
    """Tests for ``update_library_config_fields()``."""

    @pytest.mark.unit
    def test_merges_set_and_unset_fields_before_delegating(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            update_library_config_fields(
                mock_db,
                library,
                set_fields={"watch_mode": "event"},
                unset_fields=["custom_root", "scan_error"],
            )

        update_record.assert_called_once_with(
            mock_db,
            library,
            watch_mode="event",
            custom_root=None,
            scan_error=None,
        )

    @pytest.mark.unit
    def test_returns_early_when_no_fields_provided(self) -> None:
        mock_db = MagicMock()
        library = Library(name="Main", root_path="/music")

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            update_library_config_fields(mock_db, library)

        update_record.assert_not_called()


class TestFindLibraryContainingPath:
    """Tests for ``find_library_containing_path()``."""

    @pytest.mark.unit
    def test_returns_most_specific_matching_library(self) -> None:
        mock_db = MagicMock()
        libraries = [
            Library(name="Library 1", root_path="D:/Music"),
            Library(name="Library 2", root_path="D:/Music/Rock"),
        ]
        mock_db.library.list_libraries.return_value = libraries

        result = find_library_containing_path(mock_db, "D:/Music/Rock/song.flac")

        assert result is not None
        assert result.name == "Library 2"
        assert result.root_path == "D:/Music/Rock"
        mock_db.library.list_libraries.assert_called_once_with(enabled_only=False)


class TestFindMlCompleteLibraries:
    """Tests for ``find_ml_complete_libraries()``."""

    @pytest.mark.unit
    def test_returns_empty_list_when_no_state_docs(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = []

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={},
            ) as mock_get_library_counts,
            patch("nomarr.components.library.library_records_comp.count_untagged_files") as mock_count_untagged_files,
        ):
            result = find_ml_complete_libraries(mock_db, min_files=10)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.get_pipeline_state.assert_not_called()
        mock_get_library_counts.assert_called_once_with(mock_db)
        mock_count_untagged_files.assert_not_called()

    @pytest.mark.unit
    def test_excludes_library_with_untagged_files(self) -> None:
        mock_db = MagicMock()
        library = Library(name="lib-42", root_path="/m")
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state="scanned",
            ml_state=ML_IN_PROGRESS,
            calibration_state="not_calibrated",
            tag_write_state="not_written",
        )

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={"lib-42": {"file_count": 12}},
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                return_value=5,
            ) as mock_count_untagged_files,
        ):
            result = find_ml_complete_libraries(mock_db, min_files=1)

        assert result == []
        mock_count_untagged_files.assert_called_once_with(mock_db, library)

    @pytest.mark.unit
    def test_includes_fully_tagged_library(self) -> None:
        mock_db = MagicMock()
        library = Library(name="lib-42", root_path="/m")
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.get_pipeline_state.return_value = LibraryPipelineState(
            scan_state="scanned",
            ml_state=ML_IN_PROGRESS,
            calibration_state="not_calibrated",
            tag_write_state="not_written",
        )

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={"lib-42": {"file_count": 12}},
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                return_value=0,
            ) as mock_count_untagged_files,
        ):
            result = find_ml_complete_libraries(mock_db, min_files=99)

        assert result == [{"library_id": "lib-42", "tagged_count": 12}]
        mock_count_untagged_files.assert_called_once_with(mock_db, library)

    @pytest.mark.unit
    def test_returns_only_fully_tagged_libraries_when_state_docs_are_mixed(self) -> None:
        mock_db = MagicMock()
        lib7 = Library(name="lib-7", root_path="/m7")
        lib42 = Library(name="lib-42", root_path="/m42")
        mock_db.library.list_libraries.return_value = [lib7, lib42]
        mock_db.library.get_pipeline_state.side_effect = [
            LibraryPipelineState(
                scan_state="scanned",
                ml_state=ML_IN_PROGRESS,
                calibration_state="not_calibrated",
                tag_write_state="not_written",
            ),
            LibraryPipelineState(
                scan_state="scanned",
                ml_state=ML_IN_PROGRESS,
                calibration_state="not_calibrated",
                tag_write_state="not_written",
            ),
        ]

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={
                    "lib-7": {"file_count": 3},
                    "lib-42": {"file_count": 12},
                },
            ),
            patch(
                "nomarr.components.library.library_records_comp.count_untagged_files",
                side_effect=[4, 0],
            ) as mock_count_untagged_files,
        ):
            result = find_ml_complete_libraries(mock_db, min_files=2)

        assert result == [{"library_id": "lib-42", "tagged_count": 12}]
        assert mock_count_untagged_files.call_args_list == [
            ((mock_db, lib7),),
            ((mock_db, lib42),),
        ]
