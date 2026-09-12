"""Focused tests for the smart-playlist preview workflow.

The workflow consumes mutable ``SongIdentity`` locators from the filter engine,
resolves each through ``db.library.get_song``, and emits string-valued sample
track dictionaries. No generated integer identity crosses the boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import HydratedSong
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.exceptions import PlaylistQueryError
from nomarr.workflows.navidrome import preview_smart_playlist_wf

_LIBRARY = LibraryIdentity(
    library_uuid="123e4567-e89b-42d3-a456-426614174000",
    name="test-lib",
    root_path="/music",
)


def _song(normalized_path: str) -> Song:
    """Build a semantic ``Song`` fixture (no persistence row/id)."""
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=1,
        modified_time=1,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1,
    )


def _identity(normalized_path: str) -> SongIdentity:
    return SongIdentity(library=_LIBRARY, normalized_path=normalized_path)


@pytest.mark.unit
@pytest.mark.mocked
def test_preview_returns_typed_sample_fields_for_resolved_locators() -> None:
    db = MagicMock()
    locators = [_identity("a.mp3"), _identity("b.mp3")]
    songs = {locators[0]: _song("a.mp3"), locators[1]: _song("b.mp3")}
    db.library.get_song.side_effect = lambda locator: songs.get(locator)
    hydrated = [
        HydratedSong(song=songs[locators[0]], metadata={"title": "T", "artist": "A", "album": "Al"}),
        HydratedSong(song=songs[locators[1]], metadata={}),
    ]

    with (
        patch.object(preview_smart_playlist_wf, "parse_smart_playlist_query", return_value=MagicMock()),
        patch.object(
            preview_smart_playlist_wf,
            "execute_smart_playlist_filter",
            return_value=set(locators),
        ),
        patch.object(
            preview_smart_playlist_wf,
            "hydrate_songs_with_metadata",
            return_value=hydrated,
        ),
    ):
        result = preview_smart_playlist_wf.preview_smart_playlist_workflow(db, "genre=Rock", preview_limit=5)

    assert result.total_count == 2
    assert result.query == "genre=Rock"
    sample = {track["path"]: track for track in result.sample_tracks}
    assert sample["/music/a.mp3"] == {
        "path": "/music/a.mp3",
        "title": "T",
        "artist": "A",
        "album": "Al",
    }
    # Absent metadata keys render as empty strings, never ``None`` or an id.
    assert sample["/music/b.mp3"] == {"path": "/music/b.mp3", "title": "", "artist": "", "album": ""}
    assert all(isinstance(value, str) for track in result.sample_tracks for value in track.values())


@pytest.mark.unit
@pytest.mark.mocked
def test_preview_skips_unresolved_locators_but_keeps_count() -> None:
    db = MagicMock()
    locator = _identity("a.mp3")
    db.library.get_song.return_value = None

    with (
        patch.object(preview_smart_playlist_wf, "parse_smart_playlist_query", return_value=MagicMock()),
        patch.object(
            preview_smart_playlist_wf,
            "execute_smart_playlist_filter",
            return_value={locator},
        ),
        patch.object(
            preview_smart_playlist_wf,
            "hydrate_songs_with_metadata",
            return_value=[],
        ),
    ):
        result = preview_smart_playlist_wf.preview_smart_playlist_workflow(db, "genre=Rock")

    assert result.total_count == 1
    assert result.sample_tracks == []


@pytest.mark.unit
def test_preview_empty_query_raises() -> None:
    with pytest.raises(PlaylistQueryError, match="Query cannot be empty"):
        preview_smart_playlist_wf.preview_smart_playlist_workflow(MagicMock(), "   ")
