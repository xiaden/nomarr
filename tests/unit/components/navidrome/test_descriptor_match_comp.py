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
def test_resolve_seed_descriptor_returns_unresolved_when_title_empty() -> None:
    db = MagicMock()
    db.library_files.get.many.return_value = []

    resolved, status = resolve_seed_descriptor_to_file(db, _seed(title=""))

    assert status == "descriptor_unresolved"
    assert resolved is None
    db.library_files.get.many.assert_called_once_with(artist="Artist A", limit=None)
