"""Focused typed-locator coverage for the Navidrome tag query wrapper.

``find_files_matching_tag`` delegates to the tagging analytics helper, which
projects semantic songs to UUID-bearing ``SongIdentity`` locators. The wrapper
must preserve that type end-to-end: never a ``set[int]``, generated id, or
path-to-id conversion.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.navidrome.tag_query_comp import find_files_matching_tag
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef

_LIBRARY = LibraryIdentity(
    library_uuid="123e4567-e89b-42d3-a456-426614174000",
    name="test-lib",
    root_path="/music",
)
_PROJECTION = "nomarr.components.library.library_song_query_comp.locators_for_carriers"


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
def test_find_files_matching_tag_returns_typed_locators() -> None:
    db = MagicMock()
    db.library.list_tags.return_value = [TagRef(name="nom:genre", value="Rock", namespace="nom")]
    db.library.find_songs_with_tag.return_value = [_song("a.mp3"), _song("b.mp3")]
    first, second = _identity("a.mp3"), _identity("b.mp3")

    with patch(_PROJECTION, return_value=[first, second]) as projection:
        result = find_files_matching_tag(db, name="nom:genre", operator="CONTAINS", value="Rock")

    assert result == {first, second}
    assert all(isinstance(item, SongIdentity) for item in result)
    assert not any(isinstance(item, int) for item in result)
    projection.assert_called_once()


@pytest.mark.unit
@pytest.mark.mocked
def test_find_files_matching_tag_no_matching_songs_returns_empty_set() -> None:
    db = MagicMock()
    db.library.list_tags.return_value = [TagRef(name="nom:genre", value="Jazz", namespace="nom")]
    db.library.find_songs_with_tag.return_value = []

    with patch(_PROJECTION, return_value=[]) as projection:
        result = find_files_matching_tag(db, name="nom:genre", operator="CONTAINS", value="Rock")

    assert result == set()
    projection.assert_not_called()
