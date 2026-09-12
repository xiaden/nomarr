"""Tests for deterministic playlist track matching.

The matcher consumes semantic ``TrackSong`` carriers (never raw rows/dicts) and
projects a successful match to an opaque ``nom1`` SongLocator token at the
boundary. There is no generated integer handle, no ``from_db_row`` row seam, and
no path-to-ID conversion.
"""

from __future__ import annotations

import pytest

from nomarr.components.library.song_query_types import TrackSong
from nomarr.components.playlist_import.track_matcher_comp import LibraryTrack, match_track
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.playlist_import_dto import PlaylistTrackInput
from nomarr.helpers.song_locator_codec import encode_song_locator

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


def _library_track(
    *,
    normalized_path: str,
    title: str,
    artist: str,
    album: str | None = None,
    isrc: str | None = None,
) -> LibraryTrack:
    """Build a semantic ``LibraryTrack`` from a typed ``TrackSong`` carrier."""
    metadata: dict[str, object] = {"title": title, "artist": artist}
    if album is not None:
        metadata["album"] = album
    track = TrackSong(song=_song(normalized_path), metadata=metadata, isrc=isrc)
    locator = SongIdentity(library=_LIBRARY, normalized_path=normalized_path)
    return LibraryTrack.from_track_song(locator, track)


def test_isrc_match_precedes_metadata_match() -> None:
    playlist_track = PlaylistTrackInput(title="Wrong title", artist="Wrong artist", isrc="usrc17607839")
    library_track = _library_track(
        normalized_path="song.flac",
        title="Different title",
        artist="Different artist",
        isrc="USRC17607839",
    )

    result = match_track(playlist_track, [library_track])

    assert result.status == "exact_isrc"
    assert result.confidence == 1.0
    assert result.matched_file is not None
    assert result.matched_file.file_id == encode_song_locator(library_track.song_identity)
    assert result.matched_file.file_id.startswith("nom1")
    assert result.matched_file.path == "/music/song.flac"


def test_exact_metadata_match_projects_opaque_token() -> None:
    playlist_track = PlaylistTrackInput(title="Song Title", artist="Some Artist")
    library_track = _library_track(
        normalized_path="dir/song.flac",
        title="Song Title",
        artist="Some Artist",
        album="Album",
    )

    result = match_track(playlist_track, [library_track])

    assert result.status == "exact_metadata"
    assert result.matched_file is not None
    assert result.matched_file.file_id == encode_song_locator(library_track.song_identity)
    assert result.matched_file.title == "Song Title"
    assert result.matched_file.artist == "Some Artist"
    assert result.matched_file.album == "Album"


def test_fuzzy_match_without_integer_identity() -> None:
    playlist_track = PlaylistTrackInput(title="Song Titl", artist="Some Artst")
    library_track = _library_track(normalized_path="song.flac", title="Song Title", artist="Some Artist")

    result = match_track(playlist_track, [library_track])

    assert result.status in {"fuzzy", "ambiguous"}
    assert result.matched_file is not None
    assert result.matched_file.file_id == encode_song_locator(library_track.song_identity)


def test_no_match_has_no_file_info() -> None:
    playlist_track = PlaylistTrackInput(title="Unrelated", artist="Nobody")
    library_track = _library_track(normalized_path="song.flac", title="Song Title", artist="Some Artist")

    result = match_track(playlist_track, [library_track])

    assert result.status == "not_found"
    assert result.matched_file is None
    assert result.confidence == 0.0


def test_raw_row_seam_is_removed() -> None:
    """The legacy ``from_db_row`` raw-dict seam must not exist."""
    assert not hasattr(LibraryTrack, "from_db_row")


@pytest.mark.unit
def test_missing_metadata_keys_are_absent_not_coerced() -> None:
    """A carrier with no title/artist metadata yields empty strings, no row access."""
    track = TrackSong(song=_song("song.flac"), metadata={}, isrc=None)
    locator = SongIdentity(library=_LIBRARY, normalized_path="song.flac")

    library_track = LibraryTrack.from_track_song(locator, track)

    assert library_track.title == ""
    assert library_track.artist == ""
    assert library_track.album is None
    assert library_track.file_path == "/music/song.flac"
