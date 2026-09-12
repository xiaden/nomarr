"""Focused tests for the playlist-import conversion workflow.

Covers the Q3-I semantic carrier/locator consumption: the workflow loads typed
``TrackSong`` carriers, resolves them through the public ``locators_for_carriers``
projection, drops unresolved carriers, and never converts a path to a generated
integer id.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import TrackSong
from nomarr.components.playlist_import.track_matcher_comp import LibraryTrack
from nomarr.components.playlist_import.url_parser_comp import ParsedPlaylistUrl
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.playlist_import_dto import (
    MatchedFileInfo,
    MatchResult,
    PlaylistMetadata,
    PlaylistTrackInput,
)
from nomarr.helpers.exceptions import PlaylistConversionError
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.workflows.playlist_import import convert_playlist_wf

_LIBRARY = LibraryIdentity(
    library_uuid="123e4567-e89b-42d3-a456-426614174000",
    name="test-lib",
    root_path="/music",
)
_URL = "https://www.deezer.com/playlist/1234567890"


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


def _carrier(normalized_path: str) -> TrackSong:
    return TrackSong(song=_song(normalized_path), metadata={}, isrc=None)


def _input_track(title: str) -> PlaylistTrackInput:
    return PlaylistTrackInput(title=title, artist="Artist", album="Album")


def _result(input_track: PlaylistTrackInput, status: str, normalized_path: str | None) -> MatchResult:
    matched = None
    if normalized_path is not None:
        matched = MatchedFileInfo(
            path=f"/music/{normalized_path}",
            file_id=encode_song_locator(_identity(normalized_path)),
            title=input_track.title,
            artist=input_track.artist,
            album=input_track.album,
        )
    return MatchResult(input_track=input_track, status=status, confidence=1.0, matched_file=matched)


def _metadata() -> PlaylistMetadata:
    return PlaylistMetadata(name="Mix", source_url=_URL, source_platform="deezer", track_count=2)


def _patches(
    *,
    carriers: list[TrackSong],
    locators: list[SongIdentity | None],
    results: list[MatchResult],
    input_tracks: list[PlaylistTrackInput],
):
    parsed = ParsedPlaylistUrl(platform="deezer", playlist_id="1234567890", original_url=_URL)
    return (
        patch.object(convert_playlist_wf, "parse_playlist_url", return_value=parsed),
        patch.object(convert_playlist_wf, "_fetch_playlist", return_value=(_metadata(), input_tracks)),
        patch.object(convert_playlist_wf, "get_tracks_for_matching", return_value=carriers),
        patch.object(convert_playlist_wf, "locators_for_carriers", return_value=locators),
        patch.object(convert_playlist_wf, "match_tracks", return_value=results),
    )


@pytest.mark.unit
@pytest.mark.mocked
def test_convert_builds_library_tracks_from_resolved_locators_only() -> None:
    db = MagicMock()
    input_tracks = [_input_track("One"), _input_track("Two")]
    carriers = [_carrier("a.mp3"), _carrier("b.mp3")]
    resolved = _identity("a.mp3")
    results = [_result(input_tracks[0], "exact_isrc", "a.mp3")]

    patches = _patches(carriers=carriers, locators=[resolved, None], results=results, input_tracks=input_tracks)
    with patches[0], patches[1], patches[2], patches[3], patches[4] as match_tracks:
        result = convert_playlist_wf.convert_playlist_workflow(db, _URL)

    library_tracks = match_tracks.call_args.args[1]
    assert len(library_tracks) == 1
    assert isinstance(library_tracks[0], LibraryTrack)
    assert library_tracks[0].song_identity == resolved
    assert result.total_tracks == 2
    assert result.matched_count == 1
    assert result.exact_matches == 1
    assert result.m3u_content.count("/music/a.mp3") == 1


@pytest.mark.unit
@pytest.mark.mocked
def test_convert_raises_when_no_locator_resolves() -> None:
    db = MagicMock()
    input_tracks = [_input_track("One")]
    patches = _patches(
        carriers=[_carrier("a.mp3")],
        locators=[None],
        results=[],
        input_tracks=input_tracks,
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        pytest.raises(PlaylistConversionError, match="No library tracks found"),
    ):
        convert_playlist_wf.convert_playlist_workflow(db, _URL)


@pytest.mark.unit
@pytest.mark.mocked
def test_convert_classifies_match_statuses() -> None:
    db = MagicMock()
    input_tracks = [_input_track("One"), _input_track("Two"), _input_track("Three"), _input_track("Four")]
    results = [
        _result(input_tracks[0], "exact_isrc", "a.mp3"),
        _result(input_tracks[1], "fuzzy", "b.mp3"),
        _result(input_tracks[2], "ambiguous", "c.mp3"),
        _result(input_tracks[3], "not_found", None),
    ]
    patches = _patches(
        carriers=[_carrier("a.mp3")],
        locators=[_identity("a.mp3")],
        results=results,
        input_tracks=input_tracks,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = convert_playlist_wf.convert_playlist_workflow(db, _URL)

    assert result.matched_count == 2
    assert result.exact_matches == 1
    assert result.fuzzy_matches == 1
    assert result.ambiguous_count == 1
    assert result.not_found_count == 1
