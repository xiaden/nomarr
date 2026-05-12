"""Tests for nomarr.components.tagging.tag_write_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.tagging.tag_write_comp import (
    add_song_tag,
    delete_song_tags,
    find_or_create_tag,
    relink_tag_edges,
    resolve_tag_ids,
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


class TestResolveTagIds:
    """Tests for resolve_tag_ids."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_pairs(self) -> None:
        mock_db = MagicMock()

        result = resolve_tag_ids(mock_db, [])

        assert result == {}
        mock_db.library.list_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_maps_pairs_to_tag_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_tags.return_value = [{"_id": "tags/1", "name": "genre", "value": "rock"}]

        result = resolve_tag_ids(mock_db, [("genre", "rock")])

        assert result == {("genre", "rock"): "tags/1"}
        mock_db.library.list_tags.assert_called_once_with(name="genre", value="rock", limit=1)


class TestSetSongTags:
    """Tests for set_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_existing_edges_before_inserting(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = [
            {
                "start_id": "library_files/f1",
                "e": {"_id": "edges/old", "_from": "library_files/f1", "_to": "tags/old"},
                "v": {"_id": "tags/old", "name": "genre"},
            },
        ]
        mock_db.library.find_or_create_tag.return_value = "tags/1"

        set_song_tags(mock_db, "library_files/f1", "genre", ["rock"])

        mock_db.library.get_tags_for_files_batch.assert_called_once_with(
            ["library_files/f1"],
            include_edge=True,
        )
        mock_db.library.delete_song_tag_edge_by_id.assert_called_once_with("edges/old")
        mock_db.library.upsert_song_tag_edge.assert_called_once_with("library_files/f1", "tags/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_no_insert_when_values_empty(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = [
            {
                "start_id": "library_files/f1",
                "e": {"_id": "edges/old", "_from": "library_files/f1", "_to": "tags/old"},
                "v": {"_id": "tags/old", "name": "genre"},
            },
        ]

        set_song_tags(mock_db, "library_files/f1", "genre", [])

        mock_db.library.delete_song_tag_edge_by_id.assert_called_once_with("edges/old")
        mock_db.library.upsert_song_tag_edge.assert_not_called()
        mock_db.library.find_or_create_tag.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_delete_when_no_existing_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = []
        mock_db.library.find_or_create_tag.return_value = "tags/1"

        set_song_tags(mock_db, "library_files/f1", "genre", ["rock"])

        mock_db.library.delete_song_tag_edge_by_id.assert_not_called()
        mock_db.library.upsert_song_tag_edge.assert_called_once_with("library_files/f1", "tags/1")


class TestSetSongTagsBatch:
    """Tests for set_song_tags_batch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_immediately_for_empty_entries(self) -> None:
        mock_db = MagicMock()

        set_song_tags_batch(mock_db, [])

        mock_db.library.delete_song_tag_edge_by_id.assert_not_called()
        mock_db.library.find_or_create_tag.assert_not_called()
        mock_db.library.upsert_song_tag_edge.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_processes_multiple_entries(self) -> None:
        mock_db = MagicMock()
        entries = [
            {"song_id": "library_files/a", "name": "genre", "values": ["rock"]},
            {"song_id": "library_files/b", "name": "mood", "values": ["happy"]},
        ]
        mock_db.library.get_tags_for_files_batch.return_value = [
            {
                "start_id": "library_files/a",
                "e": {"_id": "edges/genre", "_from": "library_files/a", "_to": "tags/old-genre"},
                "v": {"_id": "tags/old-genre", "name": "genre"},
            },
            {
                "start_id": "library_files/b",
                "e": {"_id": "edges/mood", "_from": "library_files/b", "_to": "tags/old-mood"},
                "v": {"_id": "tags/old-mood", "name": "mood"},
            },
        ]
        mock_db.library.find_or_create_tag.side_effect = ["tags/1", "tags/2"]

        set_song_tags_batch(mock_db, entries)

        assert mock_db.library.delete_song_tag_edge_by_id.call_args_list == [call("edges/genre"), call("edges/mood")]
        assert mock_db.library.find_or_create_tag.call_args_list == [
            call("genre", "rock"),
            call("mood", "happy"),
        ]
        assert mock_db.library.upsert_song_tag_edge.call_args_list == [
            call("library_files/a", "tags/1"),
            call("library_files/b", "tags/2"),
        ]
        mock_db.library.get_tags_for_files_batch.assert_called_once_with(
            ["library_files/a", "library_files/b"],
            include_edge=True,
        )


class TestAddSongTag:
    """Tests for add_song_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_inserts_edge_with_resolved_tag_id(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_or_create_tag.return_value = "tags/xyz"

        add_song_tag(mock_db, "library_files/f1", "genre", "rock")

        mock_db.library.upsert_song_tag_edge.assert_called_once_with("library_files/f1", "tags/xyz")


class TestDeleteSongTags:
    """Tests for delete_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_all_edges_for_song(self) -> None:
        mock_db = MagicMock()

        delete_song_tags(mock_db, "library_files/f1")

        mock_db.library.delete_song_tag_edges_for_file.assert_called_once_with("library_files/f1")


class TestRelinkTagEdges:
    """Tests for relink_tag_edges."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_moved_when_no_source_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_tag_edges_for_tags.return_value = []

        result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 0, "skipped": 0, "source_orphaned": False}
        mock_db.library.insert_song_tag_edges.assert_not_called()
        mock_db.library.delete_song_tag_edge_by_id.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_moves_edges_to_target(self) -> None:
        mock_db = MagicMock()
        source_edges = [
            {"_id": "song_has_tags/1", "_from": "library_files/a", "_to": "tags/source"},
            {"_id": "song_has_tags/2", "_from": "library_files/b", "_to": "tags/source"},
        ]
        mock_db.library.get_song_tag_edges_for_tags.return_value = source_edges
        mock_db.library.count_song_tag_edges.return_value = 0

        with patch("nomarr.components.tagging.tag_write_comp.cleanup_orphaned_tags") as mock_cleanup:
            result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 2, "skipped": 0, "source_orphaned": True}
        mock_db.library.insert_song_tag_edges.assert_called_once_with(
            [
                {"_from": "library_files/a", "_to": "tags/target"},
                {"_from": "library_files/b", "_to": "tags/target"},
            ]
        )
        assert mock_db.library.delete_song_tag_edge_by_id.call_args_list == [
            call("song_has_tags/1"),
            call("song_has_tags/2"),
        ]
        mock_cleanup.assert_called_once_with(mock_db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_already_existing_target_edges(self) -> None:
        mock_db = MagicMock()
        source_edges = [
            {"_id": "song_has_tags/1", "_from": "library_files/a", "_to": "tags/source"},
            {"_id": "song_has_tags/2", "_from": "library_files/b", "_to": "tags/source"},
        ]
        target_edges = [{"_id": "song_has_tags/3", "_from": "library_files/a", "_to": "tags/target"}]
        mock_db.library.get_song_tag_edges_for_tags.return_value = source_edges + target_edges
        mock_db.library.count_song_tag_edges.return_value = 0

        with patch("nomarr.components.tagging.tag_write_comp.cleanup_orphaned_tags"):
            result = relink_tag_edges(mock_db, "tags/source", "tags/target")

        assert result == {"moved": 1, "skipped": 1, "source_orphaned": True}
        mock_db.library.insert_song_tag_edges.assert_called_once_with(
            [{"_from": "library_files/b", "_to": "tags/target"}]
        )
        assert mock_db.library.delete_song_tag_edge_by_id.call_args_list == [
            call("song_has_tags/1"),
            call("song_has_tags/2"),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_by_song_ids(self) -> None:
        mock_db = MagicMock()
        source_edges = [
            {"_id": "song_has_tags/1", "_from": "library_files/a", "_to": "tags/source"},
            {"_id": "song_has_tags/2", "_from": "library_files/b", "_to": "tags/source"},
            {"_id": "song_has_tags/3", "_from": "library_files/c", "_to": "tags/source"},
        ]
        mock_db.library.get_song_tag_edges_for_tags.return_value = source_edges
        mock_db.library.count_song_tag_edges.return_value = 0

        with patch("nomarr.components.tagging.tag_write_comp.cleanup_orphaned_tags") as mock_cleanup:
            result = relink_tag_edges(
                mock_db,
                "tags/source",
                "tags/target",
                song_ids=["library_files/a", "library_files/b"],
            )

        assert result == {"moved": 2, "skipped": 0, "source_orphaned": True}
        mock_db.library.insert_song_tag_edges.assert_called_once_with(
            [
                {"_from": "library_files/a", "_to": "tags/target"},
                {"_from": "library_files/b", "_to": "tags/target"},
            ]
        )
        assert mock_db.library.delete_song_tag_edge_by_id.call_args_list == [
            call("song_has_tags/1"),
            call("song_has_tags/2"),
        ]
        mock_cleanup.assert_called_once_with(mock_db)
