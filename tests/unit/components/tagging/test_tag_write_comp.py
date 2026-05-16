"""Tests for nomarr.components.tagging.tag_write_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.components.tagging.tag_write_comp import (
    add_song_tag,
    delete_song_tags,
    find_or_create_tag,
    relink_tag_edges,
    set_song_tags,
    set_song_tags_batch,
)


class TestFindOrCreateTag:
    """Tests for find_or_create_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_tag_id_from_library_facade(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_or_create_tag.return_value = "tags/abc"

        result = find_or_create_tag(mock_db, "genre", "rock")

        assert result == "tags/abc"
        mock_db.library.find_or_create_tag.assert_called_once_with("genre", "rock")


class TestSetSongTags:
    """Tests for set_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_replaces_requested_tag_name_and_keeps_other_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/f1": [
                {"_id": "tags/old-genre", "name": "genre", "value": "old"},
                {"_id": "tags/mood", "name": "mood", "value": "happy"},
            ]
        }

        set_song_tags(mock_db, "library_files/f1", "genre", ["rock"])

        mock_db.library.list_file_tags_for_files.assert_called_once_with(["library_files/f1"])
        mock_db.library.replace_file_tags.assert_called_once_with(
            "library_files/f1",
            [
                {"_id": "tags/mood", "name": "mood", "value": "happy"},
                {"name": "genre", "value": "rock"},
            ],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_values_remove_only_requested_name(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/f1": [
                {"_id": "tags/old-genre", "name": "genre", "value": "old"},
                {"_id": "tags/mood", "name": "mood", "value": "happy"},
            ]
        }

        set_song_tags(mock_db, "library_files/f1", "genre", [])

        mock_db.library.replace_file_tags.assert_called_once_with(
            "library_files/f1",
            [{"_id": "tags/mood", "name": "mood", "value": "happy"}],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handles_missing_existing_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_file_tags_for_files.return_value = {}

        set_song_tags(mock_db, "library_files/f1", "genre", ["rock"])

        mock_db.library.replace_file_tags.assert_called_once_with(
            "library_files/f1",
            [{"name": "genre", "value": "rock"}],
        )


class TestSetSongTagsBatch:
    """Tests for set_song_tags_batch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_immediately_for_empty_entries(self) -> None:
        mock_db = MagicMock()

        set_song_tags_batch(mock_db, [])

        mock_db.library.list_file_tags_for_files.assert_not_called()
        mock_db.library.replace_file_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_processes_multiple_entries_per_song_with_single_replace(self) -> None:
        mock_db = MagicMock()
        entries = [
            {"song_id": "library_files/a", "name": "genre", "values": ["rock"]},
            {"song_id": "library_files/a", "name": "mood", "values": ["happy", "bright"]},
            {"song_id": "library_files/b", "name": "genre", "values": ["jazz"]},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/a": [
                {"_id": "tags/old-genre", "name": "genre", "value": "old"},
                {"_id": "tags/year", "name": "year", "value": 1999},
            ],
            "library_files/b": [
                {"_id": "tags/old-mood", "name": "mood", "value": "calm"},
            ],
        }

        set_song_tags_batch(mock_db, entries)

        mock_db.library.list_file_tags_for_files.assert_called_once_with(["library_files/a", "library_files/b"])
        assert mock_db.library.replace_file_tags.call_args_list == [
            call(
                "library_files/a",
                [
                    {"_id": "tags/year", "name": "year", "value": 1999},
                    {"name": "genre", "value": "rock"},
                    {"name": "mood", "value": "happy"},
                    {"name": "mood", "value": "bright"},
                ],
            ),
            call(
                "library_files/b",
                [
                    {"_id": "tags/old-mood", "name": "mood", "value": "calm"},
                    {"name": "genre", "value": "jazz"},
                ],
            ),
        ]


class TestAddSongTag:
    """Tests for add_song_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_appends_tag_via_replace_file_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/f1": [
                {"_id": "tags/existing", "name": "mood", "value": "happy"},
            ]
        }

        add_song_tag(mock_db, "library_files/f1", "genre", "rock")

        mock_db.library.replace_file_tags.assert_called_once_with(
            "library_files/f1",
            [
                {"_id": "tags/existing", "name": "mood", "value": "happy"},
                {"name": "genre", "value": "rock"},
            ],
        )


class TestDeleteSongTags:
    """Tests for delete_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_all_edges_for_song(self) -> None:
        mock_db = MagicMock()

        delete_song_tags(mock_db, "library_files/f1")

        mock_db.library.remove_file_tags.assert_called_once_with("library_files/f1")


class TestRelinkTagEdges:
    """Tests for relink_tag_edges."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_moved_when_no_source_tags_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_files.return_value = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/a": [{"_id": "tags/other", "name": "genre", "value": "rock"}],
            "library_files/b": [{"_id": "tags/another", "name": "mood", "value": "happy"}],
        }

        result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 0, "skipped": 0, "source_orphaned": False}
        mock_db.library.replace_tag_references.assert_not_called()
        mock_db.library.replace_selected_tag_references.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_moves_edges_to_target(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_files.return_value = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/a": [{"_id": "tags/source", "name": "genre", "value": "old-a"}],
            "library_files/b": [{"_id": "tags/source", "name": "genre", "value": "old-b"}],
        }

        result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 2, "skipped": 0, "source_orphaned": True}
        mock_db.library.replace_tag_references.assert_called_once_with("tags/source", "tags/target")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_already_existing_target_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_files.return_value = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/a": [
                {"_id": "tags/source", "name": "genre", "value": "old-a"},
                {"_id": "tags/target", "name": "genre", "value": "new-a"},
            ],
            "library_files/b": [{"_id": "tags/source", "name": "genre", "value": "old-b"}],
        }

        result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 1, "skipped": 1, "source_orphaned": True}
        mock_db.library.replace_tag_references.assert_called_once_with("tags/source", "tags/target")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_by_song_ids_and_reports_remaining_source_refs(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_files.return_value = [
            {"_id": "library_files/a"},
            {"_id": "library_files/b"},
            {"_id": "library_files/c"},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            "library_files/a": [{"_id": "tags/source", "name": "genre", "value": "old-a"}],
            "library_files/b": [
                {"_id": "tags/source", "name": "genre", "value": "old-b"},
                {"_id": "tags/target", "name": "genre", "value": "new-b"},
            ],
            "library_files/c": [{"_id": "tags/source", "name": "genre", "value": "old-c"}],
        }

        result = relink_tag_edges(
            mock_db,
            "tags/source",
            "tags/target",
            song_ids=["library_files/a", "library_files/b"],
        )

        assert result == {"moved": 1, "skipped": 1, "source_orphaned": False}
        mock_db.library.replace_selected_tag_references.assert_called_once_with(
            ["library_files/a", "library_files/b"],
            "tags/source",
            "tags/target",
        )
