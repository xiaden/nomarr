"""Tests for the descriptor match component (G locator-wire projection).

Descriptors are built from F's ID-free typed ``TaggedSong`` carrier plus a
UUID-bearing ``SongIdentity`` locator. The resolved ``nomarr_file_key`` is the
opaque canonical ``nom1`` SongLocator token — never a generated integer
``songs.id``/``file_id``. The removed ``_candidate_file_ids`` integer surface
must not resurface.
"""

from __future__ import annotations

from typing import cast

import pytest

import nomarr.components.navidrome.descriptor_match_comp as descriptor_match_comp
from nomarr.components.library.song_query_types import TaggedSong
from nomarr.components.navidrome.descriptor_match_comp import (
    TrackDescriptor,
    build_track_descriptor,
    descriptor_for_locator,
    resolve_seed_descriptor_to_file,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.helpers.dto.library_dto import FileTag
from nomarr.helpers.song_locator_codec import decode_song_locator, encode_song_locator

_UUID = "123e4567-e89b-42d3-a456-426614174000"
_LIBRARY = Library(name="test-lib", root_path="/music", library_uuid=_UUID)


def _song(normalized_path: str, *, duration_seconds: float | None = 201.0) -> Song:
    """Build a minimal semantic ``Song`` (no generated integer identity)."""
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=0,
        modified_time=0,
        duration_seconds=duration_seconds,
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


def _locator(normalized_path: str) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(library_uuid=_UUID), normalized_path=normalized_path)


def _assignments(**values: str) -> tuple[SongTagAssignment, ...]:
    return tuple(SongTagAssignment(name=name, value=value) for name, value in values.items())


def _make_db(
    songs: dict[str, Song] | None = None,
    tags: dict[str, tuple[SongTagAssignment, ...]] | None = None,
) -> object:
    from unittest.mock import MagicMock

    songs = songs or {}
    tags = tags or {}
    song_values = list(songs.values())
    db = MagicMock()
    db.library.list_libraries.return_value = [_LIBRARY]
    db.library.find_songs_with_tag_pattern.return_value = tuple(song_values)
    db.library.find_songs_with_tag.return_value = tuple(song_values)
    db.library.list_songs_by_identity.side_effect = lambda locators: [
        songs[locator.normalized_path] for locator in locators if locator.normalized_path in songs
    ]
    db.library.get_song.side_effect = lambda locator: songs.get(locator.normalized_path)
    db.library.list_song_tags_for_songs.side_effect = lambda locators: {
        locator: tags.get(locator.normalized_path, ()) for locator in locators
    }
    return db


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
def test_build_track_descriptor_projects_locator_token_not_integer() -> None:
    locator = _locator("music/42.flac")
    carrier = TaggedSong(
        song=_song("music/42.flac"),
        metadata={},
        tags=(
            FileTag(key="title", value="Song A", tag_type="string", is_nomarr=False),
            FileTag(key="artist", value="Artist A", tag_type="string", is_nomarr=False),
        ),
    )

    descriptor = build_track_descriptor(carrier, locator)

    expected = encode_song_locator(locator)
    assert descriptor["nomarr_file_key"] == expected
    assert descriptor["nomarr_file_key"] != "42"
    assert decode_song_locator(descriptor["nomarr_file_key"]).library_uuid == _UUID
    assert descriptor["title"] == "Song A"
    assert descriptor["artist"] == "Artist A"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_returns_locator_token() -> None:
    song = _song("music/1.flac")
    tags = {"music/1.flac": _assignments(title="Song A", artist="Artist A", album="Album A")}
    db = _make_db({"music/1.flac": song}, tags)

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert status == ""
    assert resolved == encode_song_locator(_locator("music/1.flac"))
    assert resolved != "1"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_uses_targeted_title_query() -> None:
    song = _song("music/1.flac")
    tags = {"music/1.flac": _assignments(title="Song A", artist="Artist A", album="Album A")}
    db = _make_db({"music/1.flac": song}, tags)

    resolve_seed_descriptor_to_file(db, _seed())

    db.library.find_songs_with_tag_pattern.assert_called_once_with("title", "Song A", limit=None)
    db.library.find_songs_with_tag.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_unresolved_when_no_candidates() -> None:
    db = _make_db({}, {})

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert resolved is None
    assert status == "descriptor_unresolved"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_uses_artist_query_when_title_empty() -> None:
    db = _make_db({}, {})

    resolved, status = resolve_seed_descriptor_to_file(db, _seed(title=""))

    assert resolved is None
    assert status == "descriptor_unresolved"
    db.library.find_songs_with_tag.assert_called_once_with(TagRef(name="artist", value="Artist A"), limit=None)


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_is_ambiguous_on_multiple_matches() -> None:
    tags = {
        "music/1.flac": _assignments(title="Song A", artist="Artist A", album="Album A"),
        "music/2.flac": _assignments(title="Song A", artist="Artist A", album="Album A"),
    }
    db = _make_db({"music/1.flac": _song("music/1.flac"), "music/2.flac": _song("music/2.flac")}, tags)

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert resolved is None
    assert status == "descriptor_ambiguous"


@pytest.mark.unit
@pytest.mark.mocked
def test_descriptor_for_locator_returns_none_when_absent() -> None:
    db = _make_db({}, {})

    assert descriptor_for_locator(db, _locator("music/missing.flac")) is None


@pytest.mark.unit
@pytest.mark.mocked
def test_removed_integer_candidate_symbol_is_absent() -> None:
    assert not hasattr(descriptor_match_comp, "_candidate_file_ids")
