"""Tests for descriptor match component."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

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
async def test_resolve_seed_descriptor_uses_targeted_title_query() -> None:
    db = AsyncMock()
    db.library.search_files_by_tag_pattern = AsyncMock(return_value=[{"id": "1"}])
    db.library.search_files_by_tag.return_value = []

    resolved, status = await resolve_seed_descriptor_to_file(db, _seed())

    assert status == "descriptor_unresolved"
    assert resolved is None
    db.library.search_files_by_tag_pattern.assert_called_once_with("title", "Song A")
    db.library.search_files_by_tag.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
async def test_resolve_seed_descriptor_returns_unresolved_when_title_empty() -> None:
    db = AsyncMock()
    db.library.search_files_by_tag.return_value = []

    resolved, status = await resolve_seed_descriptor_to_file(db, _seed(title=""))

    assert status == "descriptor_unresolved"
    assert resolved is None
    db.library.search_files_by_tag.assert_called_once_with("artist", "Artist A", limit=None)
    db.library_files.get.many.assert_not_called()
