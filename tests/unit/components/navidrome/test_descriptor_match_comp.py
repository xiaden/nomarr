"""Tests for descriptor match component."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.navidrome.descriptor_match_comp import resolve_seed_descriptor_to_file


def _seed(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Song A",
        "artist": "Artist A",
        "album": "Album A",
        "album_artist": "Album Artist A",
        "duration_ms": 201000,
        "track_number": 3,
        "disc_number": 1,
        "year": 2024,
        "musicbrainz_track_id": None,
        "musicbrainz_recording_id": None,
        "nomarr_file_key": None,
    }
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_uses_targeted_title_query() -> None:
    db = MagicMock()
    db.library_files.get.many.return_value = [{"_id": "library_files/1"}]
    db.library_files.song_has_tags.by_ids.return_value = [
        {"start_id": "library_files/1", "v": {"name": "album_artist", "value": "Album Artist A"}},
        {"start_id": "library_files/1", "v": {"name": "tracknumber", "value": "3"}},
        {"start_id": "library_files/1", "v": {"name": "discnumber", "value": "1"}},
    ]
    db.library_contains_file.get.in_.return_value = []
    db.tags.get.return_value = []
    db.song_has_tags.get.in_.return_value = []
    db.library_files.get.in_.return_value = [
        {
            "_id": "library_files/1",
            "title": "Song A",
            "artist": "Artist A",
            "album": "Album A",
            "duration_seconds": 201.0,
            "year": 2024,
        }
    ]

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert status == ""
    assert resolved == "library_files/1"
    db.library_files.get.many.assert_called_once_with(title="Song A", limit=None)


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_prefers_musicbrainz_tag_lookup() -> None:
    db = MagicMock()
    def _tags_get(*, name: str, value: str, limit: int | None) -> list[dict[str, str]]:
        if name == "musicbrainz_trackid" and value == "mb-track-id":
            return [{"_id": "tags/track-id"}]
        return []

    db.tags.get.side_effect = _tags_get
    db.song_has_tags.get.in_.return_value = [{"_from": "library_files/mb"}]
    db.library_files.song_has_tags.by_ids.return_value = [
        {"start_id": "library_files/mb", "v": {"name": "musicbrainz_trackid", "value": "mb-track-id"}}
    ]
    db.library_contains_file.get.in_.return_value = []
    db.library_files.get.in_.return_value = [
        {
            "_id": "library_files/mb",
            "title": "MB Song",
            "artist": "Artist A",
            "album": "Album A",
            "duration_seconds": 201.0,
            "year": 2024,
        }
    ]

    resolved, status = resolve_seed_descriptor_to_file(db, _seed(musicbrainz_track_id="mb-track-id", title=""))

    assert status == ""
    assert resolved == "library_files/mb"
    db.library_files.get.many.assert_not_called()
