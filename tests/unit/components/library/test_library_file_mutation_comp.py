"""Tests for nomarr.components.library.library_file_mutation_comp."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_file_mutation_comp import (
    bulk_delete_files,
    delete_library_file,
    get_file_library_key,
    set_chromaprint,
    update_file_modified_time,
    update_file_path,
    update_last_tagged_at,
    update_metadata_cache,
    upsert_batch,
    upsert_library_file,
)


class TestUpsertBatch:
    """Tests for batch library-file mutation writes."""

    @pytest.mark.unit
    def test_empty_input_returns_empty_list_without_db_calls(self) -> None:
        mock_db = MagicMock()

        result = upsert_batch(mock_db, [])

        assert result == []
        mock_db.library.add_files_to_library.assert_not_called()

    @pytest.mark.unit
    def test_batch_groups_payloads_by_library_and_preserves_input_order(self) -> None:
        mock_db = MagicMock()
        mock_db.library.add_files_to_library.side_effect = [
            ["library_files/rock-existing", "library_files/rock-new"],
            ["library_files/jazz-new"],
        ]
        file_docs: list[dict[str, Any]] = [
            {
                "library_id": "libraries/rock",
                "path": "C:/music/existing.mp3",
                "library_key": "rock",
                "normalized_path": "existing.mp3",
                "file_size": 111,
                "modified_time": 1000,
            },
            {
                "library_id": "libraries/jazz",
                "path": "C:/music/jazz.mp3",
                "library_key": "jazz",
                "normalized_path": "jazz.mp3",
                "file_size": 222,
                "modified_time": 2000,
            },
            {
                "library_id": "libraries/rock",
                "path": "C:/music/new.mp3",
                "library_key": "rock",
                "normalized_path": "new.mp3",
                "file_size": 333,
                "modified_time": 3000,
            },
        ]

        result = upsert_batch(mock_db, file_docs)

        assert result == [
            "library_files/rock-existing",
            "library_files/jazz-new",
            "library_files/rock-new",
        ]
        assert mock_db.library.add_files_to_library.call_args_list == [
            call(
                "libraries/rock",
                [
                    {
                        "path": "C:/music/existing.mp3",
                        "library_key": "rock",
                        "normalized_path": "existing.mp3",
                        "file_size": 111,
                        "modified_time": 1000,
                    },
                    {
                        "path": "C:/music/new.mp3",
                        "library_key": "rock",
                        "normalized_path": "new.mp3",
                        "file_size": 333,
                        "modified_time": 3000,
                    },
                ],
            ),
            call(
                "libraries/jazz",
                [
                    {
                        "path": "C:/music/jazz.mp3",
                        "library_key": "jazz",
                        "normalized_path": "jazz.mp3",
                        "file_size": 222,
                        "modified_time": 2000,
                    }
                ],
            ),
        ]

    @pytest.mark.unit
    def test_batch_requires_library_id_for_each_doc(self) -> None:
        mock_db = MagicMock()
        file_docs: list[dict[str, Any]] = [
            {
                "library_id": None,
                "path": "C:/music/first.mp3",
                "normalized_path": "first.mp3",
                "file_size": 100,
                "modified_time": 1000,
            },
            {
                "library_id": "libraries/jazz",
                "path": "C:/music/second.mp3",
                "normalized_path": "second.mp3",
                "file_size": 200,
                "modified_time": 2000,
            },
        ]

        with pytest.raises(ValueError, match="library_id is required for upsert_batch"):
            upsert_batch(mock_db, file_docs)

        mock_db.library.add_files_to_library.assert_not_called()


class TestDeleteLibraryFile:
    """Tests for single-file deletion cleanup."""

    @pytest.mark.unit
    def test_deletes_file_id_via_library_intent(self) -> None:
        mock_db = MagicMock()

        delete_library_file(mock_db, "library_files/123")

        mock_db.library.remove_file.assert_called_once_with("library_files/123")
        mock_db.library.remove_file_by_path.assert_not_called()

    @pytest.mark.unit
    def test_resolves_path_delete_via_path_intent(self) -> None:
        mock_db = MagicMock()

        delete_library_file(mock_db, "C:/music/song.mp3")

        mock_db.library.remove_file_by_path.assert_called_once_with("C:/music/song.mp3")
        mock_db.library.remove_file.assert_not_called()


class TestBulkDeleteFiles:
    """Tests for bulk deletion cleanup."""

    @pytest.mark.unit
    def test_bulk_delete_resolves_paths_and_removes_each_found_file_once(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_file_by_path_any_library.side_effect = [
            {"_id": "library_files/a"},
            None,
            {"_id": "library_files/c"},
        ]

        result = bulk_delete_files(mock_db, ["C:/music/a.mp3", "C:/music/missing.mp3", "C:/music/c.mp3"])

        assert result == 2
        assert mock_db.library.find_file_by_path_any_library.call_args_list == [
            call("C:/music/a.mp3"),
            call("C:/music/missing.mp3"),
            call("C:/music/c.mp3"),
        ]
        assert mock_db.library.remove_file_by_path.call_args_list == [
            call("C:/music/a.mp3"),
            call("C:/music/c.mp3"),
        ]

    @pytest.mark.unit
    def test_bulk_delete_returns_zero_when_no_paths_match(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_file_by_path_any_library.return_value = None

        result = bulk_delete_files(mock_db, ["C:/music/missing.mp3"])

        assert result == 0
        mock_db.library.remove_file_by_path.assert_not_called()


class TestUpsertLibraryFile:
    """Tests for single-file insert/update writes."""

    @pytest.mark.unit
    def test_adds_file_to_library_with_expected_payload(self) -> None:
        mock_db = MagicMock()
        mock_db.library.add_file_to_library.return_value = "library_files/123"
        mock_path = MagicMock()
        mock_path.is_valid.return_value = True
        mock_path.relative = "relative/song.mp3"
        mock_path.absolute = "C:/music/song.mp3"

        with (
            patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms,
            patch(
                "nomarr.components.library.library_file_mutation_comp.library_key_from_ref",
                return_value="lib_key",
            ) as mock_library_key_from_ref,
        ):
            mock_now_ms.return_value.value = 1000
            result = upsert_library_file(
                mock_db,
                mock_path,
                "libraries/1",
                file_size=1234,
                modified_time=5678,
            )

        assert result == "library_files/123"
        mock_library_key_from_ref.assert_called_once_with("libraries/1")
        mock_db.library.add_file_to_library.assert_called_once_with(
            "libraries/1",
            {
                "path": "C:/music/song.mp3",
                "library_key": "lib_key",
                "normalized_path": "relative/song.mp3",
                "file_size": 1234,
                "modified_time": 5678,
                "duration_seconds": None,
                "artist": None,
                "album": None,
                "title": None,
                "scanned_at": 1000,
                "chromaprint": None,
                "last_tagged_at": None,
            },
        )

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_path(self) -> None:
        mock_db = MagicMock()
        mock_path = MagicMock()
        mock_path.is_valid.return_value = False
        mock_path.status = "invalid"
        mock_path.reason = "bad path"

        with pytest.raises(ValueError, match=r"Cannot upsert invalid path \(invalid\): bad path"):
            upsert_library_file(
                mock_db,
                mock_path,
                "libraries/1",
                file_size=1234,
                modified_time=5678,
            )

        mock_db.library.add_file_to_library.assert_not_called()


class TestUpdateFilePath:
    """Tests for moved-file path updates."""

    @pytest.mark.unit
    def test_updates_path_and_core_metadata(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 2000
            update_file_path(
                mock_db,
                "library_files/123",
                "C:/music/new-song.mp3",
                file_size=4321,
                modified_time=8765,
                artist="Artist",
                album="Album",
                title="Title",
                duration_seconds=123.4,
            )

        mock_db.library.update_library_file_path.assert_called_once_with(
            "library_files/123",
            "C:/music/new-song.mp3",
        )
        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {
                "file_size": 4321,
                "modified_time": 8765,
                "is_valid": 1,
                "artist": "Artist",
                "album": "Album",
                "title": "Title",
                "duration_seconds": 123.4,
                "scanned_at": 2000,
            },
        )

    @pytest.mark.unit
    def test_includes_normalized_path_when_provided(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 2000
            update_file_path(
                mock_db,
                "library_files/123",
                "C:/music/new-song.mp3",
                file_size=4321,
                modified_time=8765,
                normalized_path="relative/new-song.mp3",
            )

        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {
                "file_size": 4321,
                "modified_time": 8765,
                "is_valid": 1,
                "artist": None,
                "album": None,
                "title": None,
                "duration_seconds": None,
                "scanned_at": 2000,
                "normalized_path": "relative/new-song.mp3",
            },
        )


class TestUpdateFileModifiedTime:
    """Tests for modified-time updates after file writes."""

    @pytest.mark.unit
    def test_updates_modified_time_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        update_file_modified_time(mock_db, "abc123", 7777)

        mock_db.library.update_file.assert_called_once_with(
            "library_files/abc123",
            {"modified_time": 7777},
        )


class TestUpdateMetadataCache:
    """Tests for embedded metadata cache writes."""

    @pytest.mark.unit
    def test_updates_all_cached_metadata_fields(self) -> None:
        mock_db = MagicMock()

        update_metadata_cache(
            mock_db,
            "library_files/123",
            artist="Artist",
            artists=["Artist", "Featured"],
            album="Album",
            labels=["Label"],
            genres=["Rock", "Indie"],
            year=1999,
        )

        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {
                "artist": "Artist",
                "artists": ["Artist", "Featured"],
                "album": "Album",
                "labels": ["Label"],
                "genres": ["Rock", "Indie"],
                "year": 1999,
            },
        )


class TestGetFileLibraryKey:
    """Tests for resolving a file's owning library key."""

    @pytest.mark.unit
    def test_returns_library_key_when_file_exists(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_files.return_value = {"library_files/abc123": "libraries/lib_key"}

        result = get_file_library_key(mock_db, "abc123")

        assert result == "lib_key"
        mock_db.library.get_library_ids_for_files.assert_called_once_with(["library_files/abc123"])

    @pytest.mark.unit
    def test_returns_none_when_file_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_files.return_value = {}

        result = get_file_library_key(mock_db, "abc123")

        assert result is None
        mock_db.library.get_library_ids_for_files.assert_called_once_with(["library_files/abc123"])


class TestSetChromaprint:
    """Tests for chromaprint persistence."""

    @pytest.mark.unit
    def test_updates_chromaprint_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        set_chromaprint(mock_db, "abc123", "chromaprint-value")

        mock_db.library.update_file.assert_called_once_with(
            "library_files/abc123",
            {"chromaprint": "chromaprint-value"},
        )


class TestUpdateLastTaggedAt:
    """Tests for tag-timestamp updates."""

    @pytest.mark.unit
    def test_updates_last_tagged_at_with_current_timestamp(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 9999
            update_last_tagged_at(mock_db, "library_files/123")

        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {"last_tagged_at": 9999},
        )
