"""Tests for descriptor match component."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from nomarr.components.navidrome.descriptor_match_comp import TrackDescriptor, resolve_seed_descriptor_to_file


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
    db.library.search_files_by_text.return_value = [{"_id": "library_files/1"}]
    db.library.list_file_tags_for_files.return_value = {
        "library_files/1": [
            {"name": "album_artist", "value": "Album Artist A"},
            {"name": "tracknumber", "value": "3"},
            {"name": "discnumber", "value": "1"},
        ]
    }
    db.library.list_files_by_ids.return_value = [
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
    db.library.search_files_by_text.assert_called_once_with("title", "Song A", limit=None)
    db.library_files.get.many.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_returns_unresolved_when_title_empty() -> None:
    db = MagicMock()
    db.library.search_files_by_tag.return_value = []

    resolved, status = resolve_seed_descriptor_to_file(db, _seed(title=""))

    assert status == "descriptor_unresolved"
    assert resolved is None
    db.library.search_files_by_tag.assert_called_once_with("artist", "Artist A", limit=None)
    db.library_files.get.many.assert_not_called()
