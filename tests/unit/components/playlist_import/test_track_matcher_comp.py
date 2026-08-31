"""Tests for deterministic playlist track matching."""

from __future__ import annotations

import pytest

from nomarr.components.playlist_import.track_matcher_comp import LibraryTrack, match_track
from nomarr.helpers.dto.playlist_import_dto import PlaylistTrackInput


@pytest.mark.unit
def test_isrc_match_precedes_metadata_match() -> None:
    playlist_track = PlaylistTrackInput(title="Wrong title", artist="Wrong artist", isrc="usrc17607839")
    library_track = LibraryTrack.from_db_row(
        {
            "id": 42,
            "path": "/music/song.flac",
            "title": "Different title",
            "artist": "Different artist",
            "isrc": "USRC17607839",
        }
    )

    result = match_track(playlist_track, [library_track])

    assert result.status == "exact_isrc"
    assert result.confidence == 1.0
    assert result.matched_file is not None
    assert result.matched_file.file_id == 42
