"""Tests for nomarr.components.library.library_song_mutation_comp."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_song_mutation_comp import (
    bulk_delete_songs,
    delete_library_song,
    get_song_library_key,
    set_chromaprint,
    update_last_tagged_at,
    update_song_modified_time,
    update_song_path,
    upsert_batch,
    upsert_library_song,
)


class TestUpsertBatch:
    """Tests for batch library-file mutation writes."""

    @pytest.mark.unit
    def test_empty_input_returns_empty_list_without_db_calls(self) -> None:
        mock_db = MagicMock()

        result = upsert_batch(mock_db, [])

        assert result == []
        mock_db.library.add_songs_to_library.assert_not_called()

    @pytest.mark.unit
    def test_batch_groups_payloads_by_library_and_preserves_input_order(self) -> None:
        mock_db = MagicMock()
        mock_db.library.add_songs_to_library.side_effect = [
            [f"{'songs'}/rock-existing", f"{'songs'}/rock-new"],
            [f"{'songs'}/jazz-new"],
        ]
        file_docs: list[dict[str, Any]] = [
            {
                "library_id": 1,
                "path": "C:/music/existing.mp3",
                "normalized_path": "existing.mp3",
                "file_size": 111,
                "modified_time": 1000,
            },
            {
                "library_id": 2,
                "path": "C:/music/jazz.mp3",
                "normalized_path": "jazz.mp3",
                "file_size": 222,
                "modified_time": 2000,
            },
            {
                "library_id": 1,
                "path": "C:/music/new.mp3",
                "normalized_path": "new.mp3",
                "file_size": 333,
                "modified_time": 3000,
            },
        ]

        result = upsert_batch(mock_db, file_docs)

        assert result == [
            f"{'songs'}/rock-existing",
            f"{'songs'}/jazz-new",
            f"{'songs'}/rock-new",
        ]
        assert mock_db.library.add_songs_to_library.call_args_list == [
            call(
                1,
                [
                    {
                        "path": "C:/music/existing.mp3",
                        "normalized_path": "existing.mp3",
                        "file_size": 111,
                        "modified_time": 1000,
                    },
                    {
                        "path": "C:/music/new.mp3",
                        "normalized_path": "new.mp3",
                        "file_size": 333,
                        "modified_time": 3000,
                    },
                ],
            ),
            call(
                2,
                [
                    {
                        "path": "C:/music/jazz.mp3",
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

        mock_db.library.add_songs_to_library.assert_not_called()


class TestDeleteLibraryFile:
    """Tests for single-file deletion cleanup."""

    @pytest.mark.unit
    def test_deletes_file_id_via_library_intent(self) -> None:
        mock_db = MagicMock()

        delete_library_song(mock_db, 123)

        mock_db.library.remove_song.assert_called_once_with(123)
        mock_db.library.remove_song_by_path.assert_not_called()

    @pytest.mark.unit
    def test_resolves_path_delete_via_path_intent(self) -> None:
        mock_db = MagicMock()

        delete_library_song(mock_db, "C:/music/song.mp3", library_id=1)

        mock_db.library.remove_song_by_path.assert_called_once_with("C:/music/song.mp3", 1)
        mock_db.library.remove_song.assert_not_called()


class TestBulkDeleteFiles:
    """Tests for bulk deletion cleanup."""

    @pytest.mark.unit
    def test_bulk_delete_resolves_paths_and_removes_each_found_file_once(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_by_path.side_effect = [
            {"_id": f"{'songs'}/a"},
            None,
            {"_id": f"{'songs'}/c"},
        ]

        result = bulk_delete_songs(mock_db, ["C:/music/a.mp3", "C:/music/missing.mp3", "C:/music/c.mp3"], 1)

        assert result == 2
        assert mock_db.library.get_song_by_path.call_args_list == [
            call("C:/music/a.mp3", 1),
            call("C:/music/missing.mp3", 1),
            call("C:/music/c.mp3", 1),
        ]
        assert mock_db.library.remove_song_by_path.call_args_list == [
            call("C:/music/a.mp3", 1),
            call("C:/music/c.mp3", 1),
        ]

    @pytest.mark.unit
    def test_bulk_delete_returns_zero_when_no_paths_match(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_by_path.return_value = None

        result = bulk_delete_songs(mock_db, ["C:/music/missing.mp3"], 1)

        assert result == 0
        mock_db.library.remove_song_by_path.assert_not_called()


class TestUpsertLibraryFile:
    """Tests for single-file insert/update writes."""

    @pytest.mark.unit
    def test_adds_file_to_library_with_expected_payload(self) -> None:
        mock_db = MagicMock()
        mock_db.library.add_song_to_library.return_value = f"{'songs'}/123"
        mock_path = MagicMock()
        mock_path.is_valid.return_value = True
        mock_path.relative = "relative/song.mp3"
        mock_path.absolute = "C:/music/song.mp3"

        with patch("nomarr.components.library.library_song_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 1000
            result = upsert_library_song(
                mock_db,
                mock_path,
                "libraries/1",
                file_size=1234,
                modified_time=5678,
            )

        assert result == f"{'songs'}/123"
        mock_db.library.add_song_to_library.assert_called_once_with(
            "libraries/1",
            {
                "path": "C:/music/song.mp3",
                "normalized_path": "relative/song.mp3",
                "file_size": 1234,
                "modified_time": 5678,
                "duration_seconds": None,
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
            upsert_library_song(
                mock_db,
                mock_path,
                "libraries/1",
                file_size=1234,
                modified_time=5678,
            )

        mock_db.library.add_song_to_library.assert_not_called()


class TestUpdateFilePath:
    """Tests for moved-file path updates."""

    @pytest.mark.unit
    def test_updates_path_and_core_metadata(self) -> None:
        mock_db = MagicMock()

        update_song_path(
            mock_db,
            f"{'songs'}/123",
            "C:/music/new-song.mp3",
            file_size=4321,
            modified_time=8765,
            duration_seconds=123.4,
        )

        mock_db.library.update_library_song_path.assert_called_once_with(
            f"{'songs'}/123",
            "C:/music/new-song.mp3",
        )
        mock_db.library.update_library_song_scan_metadata.assert_called_once_with(
            f"{'songs'}/123",
            file_size=4321,
            modified_time=8765,
            duration_seconds=123.4,
            normalized_path=None,
        )

    @pytest.mark.unit
    def test_includes_normalized_path_when_provided(self) -> None:
        mock_db = MagicMock()

        update_song_path(
            mock_db,
            f"{'songs'}/123",
            "C:/music/new-song.mp3",
            file_size=4321,
            modified_time=8765,
            normalized_path="relative/new-song.mp3",
        )

        mock_db.library.update_library_song_scan_metadata.assert_called_once_with(
            f"{'songs'}/123",
            file_size=4321,
            modified_time=8765,
            duration_seconds=None,
            normalized_path="relative/new-song.mp3",
        )


class TestUpdateFileModifiedTime:
    """Tests for modified-time updates after file writes."""

    @pytest.mark.unit
    def test_updates_modified_time_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        update_song_modified_time(mock_db, "abc123", 7777)

        mock_db.library.update_library_song_modified_time.assert_called_once_with(
            "abc123",
            7777,
        )


class TestGetFileLibraryKey:
    """Tests for resolving a file's owning library key."""

    @pytest.mark.unit
    def test_returns_library_key_when_file_exists(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_songs.return_value = {123: 456}

        result = get_song_library_key(mock_db, 123)

        assert result == 456
        mock_db.library.get_library_ids_for_songs.assert_called_once_with([123])

    @pytest.mark.unit
    def test_returns_none_when_file_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_songs.return_value = {}

        result = get_song_library_key(mock_db, 123)

        assert result is None
        mock_db.library.get_library_ids_for_songs.assert_called_once_with([123])


class TestSetChromaprint:
    """Tests for chromaprint persistence."""

    @pytest.mark.unit
    def test_updates_chromaprint_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        set_chromaprint(mock_db, "abc123", "chromaprint-value")

        mock_db.library.set_library_song_chromaprint.assert_called_once_with(
            "abc123",
            "chromaprint-value",
        )


class TestUpdateLastTaggedAt:
    """Tests for tag-timestamp updates."""

    @pytest.mark.unit
    def test_updates_last_tagged_at_with_current_timestamp(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_song_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 9999
            update_last_tagged_at(mock_db, f"{'songs'}/123")

        mock_db.library.update_library_song_last_tagged_at.assert_called_once_with(
            f"{'songs'}/123",
            9999,
        )
