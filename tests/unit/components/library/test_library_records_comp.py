"""Tests for constructor-backed library record helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_records_comp import list_all_library_keys


class TestListAllLibraryKeys:
    """Tests for ``list_all_library_keys()``."""

    @pytest.mark.unit
    def test_returns_list_of_keys(self) -> None:
        """Returns library document keys from the constructor namespace."""
        mock_db = MagicMock()
        mock_db.libraries.count.return_value = 2
        mock_db.libraries._key.collect.return_value = ["lib1", "lib2"]

        result = list_all_library_keys(mock_db)

        assert result == ["lib1", "lib2"]

    @pytest.mark.unit
    def test_returns_empty_list_when_no_libraries(self) -> None:
        """Returns an empty list when no libraries exist."""
        mock_db = MagicMock()
        mock_db.libraries.count.return_value = 0
        mock_db.libraries._key.collect.return_value = []

        result = list_all_library_keys(mock_db)

        assert result == []


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
    def test_inserts_constructor_record_with_defaults(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.insert.return_value = ["libraries/1"]

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=123456789)
            result = create_library_record(
                mock_db,
                name="Main",
                root_path="D:/Music",
            )

        assert result == "libraries/1"
        mock_db.libraries.insert.assert_called_once_with(
            [
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
            ]
        )


class TestGetLibraryRecord:
    """Tests for ``get_library_record()``."""

    @pytest.mark.unit
    def test_gets_full_id_and_merges_scan_by_default(self) -> None:
        mock_db = MagicMock()
        library_doc = {"_id": "libraries/1", "name": "Main"}
        merged_doc = {**library_doc, "scan_status": "idle"}
        mock_db.libraries.get.return_value = library_doc

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            return_value=merged_doc,
        ) as merge_scan:
            result = get_library_record(mock_db, "libraries/1")

        assert result == merged_doc
        mock_db.libraries.get.assert_called_once_with("libraries/1")
        merge_scan.assert_called_once_with(mock_db, library_doc)

    @pytest.mark.unit
    def test_gets_by_key_without_merge_when_scan_disabled(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries._key.get.return_value = {"_id": "libraries/2", "name": "Alt"}

        result = get_library_record(mock_db, "2", include_scan=False)

        assert result == {"_id": "libraries/2", "name": "Alt"}
        mock_db.libraries._key.get.assert_called_once_with("2")


class TestGetLibraryByName:
    """Tests for ``get_library_by_name()``."""

    @pytest.mark.unit
    def test_merges_scan_state_when_requested(self) -> None:
        mock_db = MagicMock()
        library_doc = {"_id": "libraries/1", "name": "Main"}
        merged_doc = {**library_doc, "scan_status": "running"}
        mock_db.libraries.name.get.return_value = library_doc

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            return_value=merged_doc,
        ) as merge_scan:
            result = get_library_by_name(mock_db, "Main", include_scan=True)

        assert result == merged_doc
        mock_db.libraries.name.get.assert_called_once_with("Main")
        merge_scan.assert_called_once_with(mock_db, library_doc)


class TestListLibraryRecords:
    """Tests for ``list_library_records()``."""

    @pytest.mark.unit
    def test_collects_all_docs_sorts_by_created_at_and_skips_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.count.return_value = 3
        mock_db.libraries._id.collect.return_value = ["libraries/2", "libraries/missing", "libraries/1"]
        mock_db.libraries.get.side_effect = [
            {"_id": "libraries/2", "created_at": 20},
            None,
            {"_id": "libraries/1", "created_at": 10},
        ]

        result = list_library_records(mock_db, include_scan=False)

        assert result == [
            {"_id": "libraries/1", "created_at": 10},
            {"_id": "libraries/2", "created_at": 20},
        ]
        mock_db.libraries._id.collect.assert_called_once_with(limit=3)

    @pytest.mark.unit
    def test_merges_scan_state_for_enabled_only_records(self) -> None:
        mock_db = MagicMock()
        enabled_docs = [{"_id": "libraries/1", "created_at": 10}]
        merged_docs = [{"_id": "libraries/1", "created_at": 10, "scan_status": "idle"}]
        mock_db.libraries.is_enabled.get.return_value = enabled_docs

        with patch(
            "nomarr.components.library.library_records_comp._merge_scan_state",
            side_effect=merged_docs,
        ) as merge_scan:
            result = list_library_records(mock_db, enabled_only=True)

        assert result == merged_docs
        mock_db.libraries.is_enabled.get.assert_called_once_with(True)
        merge_scan.assert_called_once_with(mock_db, enabled_docs[0])


class TestListWatchableLibraryRecords:
    """Tests for ``list_watchable_library_records()``."""

    @pytest.mark.unit
    def test_filters_off_modes_and_projects_watch_fields(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/1", "root_path": "D:/Music", "watch_mode": "poll"},
            {"_id": "libraries/2", "root_path": "D:/Audiobooks", "watch_mode": "off"},
            {"_id": "libraries/3", "root_path": "D:/Podcasts", "watch_mode": None},
        ]

        with patch(
            "nomarr.components.library.library_records_comp.list_library_records",
            return_value=libraries,
        ) as list_records:
            result = list_watchable_library_records(mock_db)

        assert result == [{"_id": "libraries/1", "root_path": "D:/Music", "watch_mode": "poll"}]
        list_records.assert_called_once_with(mock_db, enabled_only=True, include_scan=False)


class TestUpdateLibraryRecord:
    """Tests for ``update_library_record()``."""

    @pytest.mark.unit
    def test_updates_normalized_library_id_with_non_none_fields(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_records_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock(value=222333444)
            update_library_record(
                mock_db,
                "main",
                name="Renamed",
                watch_mode="poll",
                description=None,
            )

        mock_db.libraries._id.update.assert_called_once_with(
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
    def test_merges_set_and_unset_fields_before_delegating(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            update_library_config_fields(
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
    def test_returns_early_when_no_fields_provided(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_records_comp.update_library_record") as update_record:
            update_library_config_fields(mock_db, "libraries/1")

        update_record.assert_not_called()


class TestFindLibraryContainingPath:
    """Tests for ``find_library_containing_path()``."""

    @pytest.mark.unit
    def test_returns_most_specific_matching_library(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/root", "root_path": "D:/Music"},
            {"_id": "libraries/nested", "root_path": "D:/Music/Rock"},
        ]

        with patch(
            "nomarr.components.library.library_records_comp.list_library_records",
            return_value=libraries,
        ) as list_records:
            result = find_library_containing_path(mock_db, "D:/Music/Rock/song.flac")

        assert result == {"_id": "libraries/nested", "root_path": "D:/Music/Rock"}
        list_records.assert_called_once_with(mock_db, enabled_only=False, include_scan=False)


from unittest.mock import patch  # noqa: E402

from nomarr.components.library.library_records_comp import (  # noqa: E402
    PIPELINE_ML_RUNNING,
    create_library_record,
    find_library_containing_path,
    find_ml_complete_libraries,
    get_library_by_name,
    get_library_record,
    library_key_from_ref,
    list_library_records,
    list_watchable_library_records,
    normalize_library_id,
    update_library_config_fields,
    update_library_record,
)


class TestFindMlCompleteLibraries:
    """Tests for ``find_ml_complete_libraries()``."""

    @pytest.mark.unit
    def test_returns_empty_list_when_no_state_docs(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.count.return_value = 0
        mock_db.library_pipeline_states.pipeline_state.get.many.return_value = []

        with (
            patch(
                "nomarr.components.library.library_records_comp.get_library_counts",
                return_value={},
            ) as mock_get_library_counts,
            patch("nomarr.components.library.library_records_comp.count_untagged_files") as mock_count_untagged_files,
        ):
            result = find_ml_complete_libraries(mock_db, min_files=10)

        assert result == []
        mock_db.library_pipeline_states.pipeline_state.get.many.assert_called_once_with(
            PIPELINE_ML_RUNNING,
            limit=0,
        )
        mock_get_library_counts.assert_called_once_with(mock_db)
        mock_count_untagged_files.assert_not_called()

    @pytest.mark.unit
    def test_excludes_library_with_untagged_files(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.count.return_value = 1
        mock_db.library_pipeline_states.pipeline_state.get.many.return_value = [{"library_key": "42"}]

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
            result = find_ml_complete_libraries(mock_db, min_files=1)

        assert result == []
        mock_count_untagged_files.assert_called_once_with(mock_db, "libraries/42")

    @pytest.mark.unit
    def test_includes_fully_tagged_library(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.count.return_value = 1
        mock_db.library_pipeline_states.pipeline_state.get.many.return_value = [{"library_key": "42"}]

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
            result = find_ml_complete_libraries(mock_db, min_files=99)

        assert result == [{"library_id": "libraries/42", "tagged_count": 12}]
        mock_count_untagged_files.assert_called_once_with(mock_db, "libraries/42")

    @pytest.mark.unit
    def test_returns_only_fully_tagged_libraries_when_state_docs_are_mixed(self) -> None:
        mock_db = MagicMock()
        mock_db.library_pipeline_states.count.return_value = 2
        mock_db.library_pipeline_states.pipeline_state.get.many.return_value = [
            {"library_key": "7"},
            {"library_key": "42"},
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
            result = find_ml_complete_libraries(mock_db, min_files=2)

        assert result == [{"library_id": "libraries/42", "tagged_count": 12}]
        assert mock_count_untagged_files.call_args_list == [
            ((mock_db, "libraries/7"),),
            ((mock_db, "libraries/42"),),
        ]
