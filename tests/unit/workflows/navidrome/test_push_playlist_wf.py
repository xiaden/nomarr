"""Unit tests for push_playlist_wf."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.navidrome_dto import PushPlaylistResult
from nomarr.workflows.navidrome.push_playlist_wf import push_playlist


def _make_db(id_map: dict[str, str]) -> MagicMock:
    """Create a mock Database with navidrome_tracks.bulk_resolve_files_to_nd."""
    db = MagicMock()
    db.navidrome_tracks.bulk_resolve_files_to_nd.return_value = id_map
    return db


def _make_client(
    playlists: list[dict[str, str]] | None = None,
    created_id: str = "pl-new-123",
) -> MagicMock:
    """Create a mock SubsonicClient with get_playlists and create_or_replace_playlist."""
    client = MagicMock()
    client.get_playlists.return_value = playlists or []
    client.create_or_replace_playlist.return_value = {
        "playlist": {"id": created_id, "name": "test"},
    }
    return client


@pytest.mark.unit
class TestPushPlaylistCreateNew:
    """Tests for creating a new playlist (no existing match)."""

    def test_creates_new_playlist(self) -> None:
        db = _make_db({"f1": "nd1", "f2": "nd2"})
        client = _make_client(playlists=[], created_id="pl-abc")

        result = push_playlist(db, client, "My Playlist", ["f1", "f2"])

        assert isinstance(result, PushPlaylistResult)
        assert result.resolved_count == 2
        assert result.unresolved_count == 0
        assert result.playlist_id == "pl-abc"
        client.create_or_replace_playlist.assert_called_once_with(
            name="My Playlist",
            song_ids=["nd1", "nd2"],
            playlist_id=None,
        )

    def test_no_match_among_existing_playlists(self) -> None:
        db = _make_db({"f1": "nd1"})
        client = _make_client(
            playlists=[{"id": "pl-other", "name": "Other Playlist"}],
            created_id="pl-new",
        )

        result = push_playlist(db, client, "My Playlist", ["f1"])

        assert result.playlist_id == "pl-new"
        client.create_or_replace_playlist.assert_called_once_with(
            name="My Playlist",
            song_ids=["nd1"],
            playlist_id=None,
        )


@pytest.mark.unit
class TestPushPlaylistReplaceExisting:
    """Tests for replacing an existing playlist by name."""

    def test_replaces_case_insensitive_match(self) -> None:
        db = _make_db({"f1": "nd1", "f2": "nd2"})
        client = _make_client(
            playlists=[{"id": "pl-exist", "name": "my playlist"}],
            created_id="pl-exist",
        )

        result = push_playlist(db, client, "My Playlist", ["f1", "f2"])

        assert result.resolved_count == 2
        client.create_or_replace_playlist.assert_called_once_with(
            name="My Playlist",
            song_ids=["nd1", "nd2"],
            playlist_id="pl-exist",
        )


@pytest.mark.unit
class TestPushPlaylistPartialResolution:
    """Tests for partial file ID resolution."""

    def test_partial_resolution_pushes_resolved_only(self) -> None:
        db = _make_db({"f1": "nd1"})  # f2 has no mapping
        client = _make_client(created_id="pl-partial")

        result = push_playlist(db, client, "Partial", ["f1", "f2"])

        assert result.resolved_count == 1
        assert result.unresolved_count == 1
        client.create_or_replace_playlist.assert_called_once_with(
            name="Partial",
            song_ids=["nd1"],
            playlist_id=None,
        )

    def test_no_resolvable_ids_skips_push(self) -> None:
        db = _make_db({})  # no mappings at all
        client = _make_client()

        result = push_playlist(db, client, "Empty", ["f1", "f2"])

        assert result.resolved_count == 0
        assert result.unresolved_count == 2
        assert result.playlist_id == ""
        client.create_or_replace_playlist.assert_not_called()
