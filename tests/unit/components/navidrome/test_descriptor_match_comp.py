"""Tests for descriptor match component."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.navidrome.descriptor_match_comp import (
    TrackDescriptor,
    _candidate_file_ids,
    build_track_descriptor,
    resolve_seed_descriptor_to_file,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef


def _song(song_id: int) -> Song:
    """Build a minimal domain ``Song`` for facade song-read mocks."""
    return Song(
        song_id=song_id,
        library_id=1,
        folder_id=None,
        path=f"/music/{song_id}.flac",
        normalized_path=f"music/{song_id}.flac",
        file_size=0,
        modified_time=0,
        duration_seconds=201.0,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=0,
    )


def _seed(**overrides: object) -> TrackDescriptor:
    base: dict[str, object] = {
        "title": "Song A",
        "artist": "Artist A",
        "album": "Album A",
        "album_artist": "Album Artist A",
        "duration_ms": 201000,
        "track_number": 3,
        "disc_number": 1,
        "year": 2024,
        "nomarr_file_key": None,
    }
    base.update(overrides)
    return cast("TrackDescriptor", base)


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_uses_targeted_title_query() -> None:
    db = MagicMock()
    db.library.find_songs_with_tag_pattern = MagicMock(return_value=(_song(1),))
    db.library.find_songs_with_tag.return_value = ()

    with patch(
        "nomarr.components.navidrome.descriptor_match_comp.get_songs_by_ids_with_tags",
        return_value=[
            {
                "id": 1,
                "duration_seconds": 201.0,
                "tags": [
                    {"key": "title", "value": "Song A"},
                    {"key": "artist", "value": "Artist A"},
                    {"key": "album", "value": "Album A"},
                    {"key": "album_artist", "value": "Album Artist A"},
                ],
            },
        ],
    ) as mock_get_songs:
        resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert status == ""
    assert resolved == "1"
    mock_get_songs.assert_called_once_with(db, [1])
    db.library.find_songs_with_tag_pattern.assert_called_once_with("title", "Song A", limit=None)
    db.library.find_songs_with_tag.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_build_track_descriptor_uses_integer_song_id_as_file_key() -> None:
    descriptor = build_track_descriptor(
        {
            "id": 42,
            "tags": [{"key": "title", "value": "Song A"}, {"key": "artist", "value": "Artist A"}],
        },
    )

    assert descriptor["nomarr_file_key"] == "42"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_returns_unresolved_when_title_empty() -> None:
    db = MagicMock()
    db.library.find_songs_with_tag = MagicMock(return_value=(_song(7),))

    assert _candidate_file_ids(db, _seed(title="")) == {"7"}
    db.library.find_songs_with_tag.reset_mock()
    resolved, status = resolve_seed_descriptor_to_file(db, _seed(title=""))

    assert status == "descriptor_unresolved"
    assert resolved is None
    db.library.find_songs_with_tag.assert_called_once_with(TagRef(name="artist", value="Artist A"), limit=None)
