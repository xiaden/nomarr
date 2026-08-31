"""Tests for nomarr.components.tagging.tag_write_comp module.

Phase 6 rewrite: asserts the migrated domain-facing API. All writes route
through the sealed ``LibraryTagsDb`` facade using ``SongIdentity`` /
``TagRef`` and typed ``SongTagAssignment`` commands / ``RelinkResult``
results. Numeric song handles are translated with the identity bridge
(``db.library.resolve_song_identity(s)`` / ``resolve_song_identities``). The
deleted ``find_or_create_tag`` and raw replacement-dict/edge-scan behavior are
gone from this layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.components.tagging.tag_write_comp import (
    add_song_tag,
    delete_song_tags,
    relink_tag_edges,
    set_song_tags,
    set_song_tags_batch,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import RelinkResult, SongTagAssignment, TagRef


def _song_identity(song_id: int) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(name="Music", root_path="/music"),
        normalized_path=f"song{song_id}.mp3",
    )


class TestSetSongTags:
    """Tests for set_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_replaces_requested_tag_name_and_keeps_other_tags(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="old"),
            SongTagAssignment(name="mood", value="happy", namespace="default"),
        )

        set_song_tags(mock_db, 1, "genre", ["rock"])

        mock_db.library.resolve_song_identity.assert_called_once_with(1)
        mock_db.library.list_tags_for_song.assert_called_once_with(song_identity)
        mock_db.library.replace_song_tags.assert_called_once_with(
            song_identity,
            [
                SongTagAssignment(name="mood", value="happy", namespace="default"),
                SongTagAssignment(name="genre", value="rock", namespace="default"),
            ],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_values_remove_only_requested_name(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="old"),
            SongTagAssignment(name="mood", value="happy", namespace="default"),
        )

        set_song_tags(mock_db, 1, "genre", [])

        mock_db.library.replace_song_tags.assert_called_once_with(
            song_identity,
            [SongTagAssignment(name="mood", value="happy", namespace="default")],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handles_missing_existing_tags(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = ()

        set_song_tags(mock_db, 1, "genre", ["rock"])

        mock_db.library.replace_song_tags.assert_called_once_with(
            song_identity,
            [SongTagAssignment(name="genre", value="rock", namespace="default")],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_noop_when_song_identity_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None

        set_song_tags(mock_db, 999, "genre", ["rock"])

        mock_db.library.list_tags_for_song.assert_not_called()
        mock_db.library.replace_song_tags.assert_not_called()


class TestSetSongTagsBatch:
    """Tests for set_song_tags_batch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_immediately_for_empty_entries(self) -> None:
        mock_db = MagicMock()

        set_song_tags_batch(mock_db, [])

        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()
        mock_db.library.replace_song_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_processes_multiple_entries_per_song_with_single_replace(self) -> None:
        mock_db = MagicMock()
        entries = [
            {"song_id": 1, "name": "genre", "values": ["rock"]},
            {"song_id": 1, "name": "mood", "values": ["happy", "bright"]},
            {"song_id": 2, "name": "genre", "values": ["jazz"]},
        ]
        id1 = _song_identity(1)
        id2 = _song_identity(2)
        mock_db.library.resolve_song_identities.return_value = {1: id1, 2: id2}
        mock_db.library.list_song_tags_for_songs.return_value = {
            id1: (
                SongTagAssignment(name="genre", value="old"),
                SongTagAssignment(name="year", value=1999, namespace="default"),
            ),
            id2: (SongTagAssignment(name="mood", value="calm", namespace="default"),),
        }

        set_song_tags_batch(mock_db, entries)

        mock_db.library.resolve_song_identities.assert_called_once_with([1, 2])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2])
        assert mock_db.library.replace_song_tags.call_args_list == [
            call(
                id1,
                [
                    SongTagAssignment(name="year", value=1999, namespace="default"),
                    SongTagAssignment(name="genre", value="rock", namespace="default"),
                    SongTagAssignment(name="mood", value="happy", namespace="default"),
                    SongTagAssignment(name="mood", value="bright", namespace="default"),
                ],
            ),
            call(
                id2,
                [
                    SongTagAssignment(name="mood", value="calm", namespace="default"),
                    SongTagAssignment(name="genre", value="jazz", namespace="default"),
                ],
            ),
        ]


class TestAddSongTag:
    """Tests for add_song_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_appends_tag_via_replace_song_tags(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="mood", value="happy", namespace="default"),
        )

        add_song_tag(mock_db, 1, "genre", "rock")

        mock_db.library.replace_song_tags.assert_called_once_with(
            song_identity,
            [
                SongTagAssignment(name="mood", value="happy", namespace="default"),
                SongTagAssignment(name="genre", value="rock", namespace="default"),
            ],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_noop_when_song_identity_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None

        add_song_tag(mock_db, 999, "genre", "rock")

        mock_db.library.list_tags_for_song.assert_not_called()
        mock_db.library.replace_song_tags.assert_not_called()


class TestDeleteSongTags:
    """Tests for delete_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_all_edges_for_song(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity

        delete_song_tags(mock_db, 1)

        mock_db.library.resolve_song_identity.assert_called_once_with(1)
        mock_db.library.remove_song_tags.assert_called_once_with(song_identity)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_noop_when_song_identity_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None

        delete_song_tags(mock_db, 999)

        mock_db.library.remove_song_tags.assert_not_called()


class TestRelinkTagEdges:
    """Tests for relink_tag_edges."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_result_when_source_equals_target(self) -> None:
        mock_db = MagicMock()
        tag = TagRef(name="genre", value="rock", namespace="default")

        result = relink_tag_edges(mock_db, tag, tag)

        assert result == RelinkResult(moved=0, skipped=0, source_orphaned=0)
        mock_db.library.relink_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_relink_to_facade(self) -> None:
        mock_db = MagicMock()
        source = TagRef(name="genre", value="old", namespace="default")
        target = TagRef(name="genre", value="rock", namespace="default")
        mock_db.library.relink_tags.return_value = RelinkResult(moved=2, skipped=0, source_orphaned=1)

        result = relink_tag_edges(mock_db, source, target)

        assert result == RelinkResult(moved=2, skipped=0, source_orphaned=1)
        mock_db.library.relink_tags.assert_called_once_with(source, target, songs=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_song_identities_when_provided(self) -> None:
        mock_db = MagicMock()
        source = TagRef(name="genre", value="old", namespace="default")
        target = TagRef(name="genre", value="rock", namespace="default")
        song_identities = [_song_identity(1), _song_identity(2)]
        mock_db.library.relink_tags.return_value = RelinkResult(moved=1, skipped=1, source_orphaned=0)

        result = relink_tag_edges(mock_db, source, target, song_identities=song_identities)

        assert result == RelinkResult(moved=1, skipped=1, source_orphaned=0)
        mock_db.library.relink_tags.assert_called_once_with(source, target, songs=song_identities)
