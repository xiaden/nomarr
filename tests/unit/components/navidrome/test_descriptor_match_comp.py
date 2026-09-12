"""Tests for the descriptor match component (G locator-wire projection).

Descriptors are built from F's ID-free typed ``TaggedSong`` carrier plus a
UUID-bearing ``SongIdentity`` locator. The resolved ``nomarr_file_key`` is the
opaque canonical ``nom1`` SongLocator token — never a generated integer
``songs.id``/``file_id``. The removed ``_candidate_file_ids`` integer surface
must not resurface.
"""

from __future__ import annotations

import ast
from inspect import getsource
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

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

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

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
) -> Database:
    songs = songs or {}
    tags = tags or {}
    song_values = list(songs.values())
    db: MagicMock = MagicMock()
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
    return cast("Database", db)


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
    assert descriptor["nomarr_file_key"] is not None
    assert decode_song_locator(descriptor["nomarr_file_key"]).library_uuid == _UUID
    assert descriptor["title"] == "Song A"
    assert descriptor["artist"] == "Artist A"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_preserves_requested_uuid_for_colliding_paths() -> None:
    other_uuid = "223e4567-e89b-42d3-a456-426614174000"
    requested = Library(name="requested", root_path="/one", library_uuid=_UUID)
    other = Library(name="other", root_path="/two", library_uuid=other_uuid)
    requested_song = _song("music/shared.flac")
    other_song = _song("music/shared.flac")
    db: MagicMock = MagicMock()
    db.library.list_libraries.return_value = [requested, other]
    db.library.find_songs_with_tag_pattern.return_value = (requested_song, other_song)
    db.library.list_songs_by_identity.side_effect = lambda locators: [
        requested_song if locator.library.library_uuid == _UUID else other_song for locator in locators
    ]
    db.library.list_song_tags_for_songs.side_effect = lambda locators: {
        locator: _assignments(title="Song A", artist="Artist A", album="Album A") for locator in locators
    }

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert status == ""
    assert resolved is not None
    assert resolved.startswith("nom1")
    assert decode_song_locator(resolved).library_uuid == _UUID
    assert decode_song_locator(resolved).path == "music/shared.flac"
    descriptor = descriptor_for_locator(db, _locator("music/shared.flac"))
    assert descriptor is not None
    assert descriptor["nomarr_file_key"] == resolved


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

    cast("MagicMock", db.library.find_songs_with_tag_pattern).assert_called_once_with("title", "Song A", limit=None)
    cast("MagicMock", db.library.find_songs_with_tag).assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_unresolved_when_no_candidates() -> None:
    db = _make_db({}, {})

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert resolved is None
    assert status == "descriptor_unresolved"


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_degrades_when_projected_carrier_is_missing() -> None:
    song = _song("music/missing.flac")
    db = _make_db({"music/missing.flac": song}, {})
    cast("MagicMock", db.library.find_songs_with_tag_pattern).return_value = (song,)
    cast("MagicMock", db.library.list_songs_by_identity).return_value = []

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
    cast("MagicMock", db.library.find_songs_with_tag).assert_called_once_with(
        TagRef(name="artist", value="Artist A"), limit=None
    )


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_normalizes_case_and_whitespace() -> None:
    song = _song("music/normalized.flac")
    tags = {"music/normalized.flac": _assignments(title="Song A", artist="Artist A")}
    db = _make_db({"music/normalized.flac": song}, tags)

    resolved, status = resolve_seed_descriptor_to_file(
        db, _seed(title="  song a  ", artist=" artist a ", album="", album_artist="")
    )

    assert status == ""
    assert resolved == encode_song_locator(_locator("music/normalized.flac"))
    assert resolved is not None
    assert decode_song_locator(resolved).library_uuid == _UUID


@pytest.mark.unit
@pytest.mark.mocked
def test_resolve_seed_descriptor_preserves_candidate_order_for_partial_projection() -> None:
    first = _song("music/first.flac")
    second = _song("music/second.flac")
    tags = {
        "music/first.flac": _assignments(title="Song A", artist="Artist A"),
        "music/second.flac": _assignments(title="Song A", artist="Artist A"),
    }
    db = _make_db({"music/first.flac": first, "music/second.flac": second}, tags)
    cast("MagicMock", db.library.find_songs_with_tag_pattern).return_value = (first, second)
    cast("MagicMock", db.library.list_songs_by_identity).side_effect = [
        [first, second],
        [first],
        [second],
    ]

    resolved, status = resolve_seed_descriptor_to_file(db, _seed())

    assert resolved is None
    assert status == "descriptor_ambiguous"
    assert cast("MagicMock", db.library.list_songs_by_identity).call_count == 3


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
def test_build_track_descriptor_prefers_tags_and_normalizes_optional_fields() -> None:
    locator = _locator("music/optional.flac")
    carrier = TaggedSong(
        song=_song("music/optional.flac", duration_seconds=None),
        metadata={"title": "Metadata title", "artist": "Metadata artist", "year": "2020"},
        tags=(
            FileTag(key="title", value="Tagged title", tag_type="string", is_nomarr=False),
            FileTag(key="artist", value="Tagged artist", tag_type="string", is_nomarr=False),
            FileTag(key="tracknumber", value="2/10", tag_type="string", is_nomarr=False),
        ),
    )

    descriptor = build_track_descriptor(carrier, locator)

    assert descriptor["title"] == "Tagged title"
    assert descriptor["artist"] == "Tagged artist"
    assert descriptor["track_number"] == 210
    assert descriptor["disc_number"] is None
    assert descriptor["year"] == 2020
    assert descriptor["duration_ms"] is None
    assert descriptor["nomarr_file_key"] == encode_song_locator(locator)


@pytest.mark.unit
@pytest.mark.mocked
def test_descriptor_for_locator_returns_none_when_absent() -> None:
    db = _make_db({}, {})

    with patch(
        "nomarr.components.navidrome.descriptor_match_comp.tagged_songs_for_locators",
        return_value=[],
    ):
        assert descriptor_for_locator(db, _locator("music/missing.flac")) is None


@pytest.mark.unit
@pytest.mark.mocked
def test_removed_integer_candidate_symbol_is_absent() -> None:
    assert not hasattr(descriptor_match_comp, "_candidate_file_ids")


def _executable_source_tokens(source: str) -> set[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.add(node.value)
    return tokens


@pytest.mark.unit
def test_descriptor_source_owns_only_semantic_projection_and_queries() -> None:
    tokens = _executable_source_tokens(getsource(descriptor_match_comp))
    assert {"TagRef", "TrackSong", "TaggedSong", "locators_for_carriers"} <= tokens
    for forbidden in (
        "SongRow",
        "row_to_domain",
        "raw_row",
        "persistence_row",
        "generated_id",
        "integer_id",
        "song_id",
        "file_id",
        "library_id",
        "folder_id",
        "resolver",
        "shim",
        "alias",
        "dual_path",
        "transaction",
        "sessionmaker",
        "MlDb",
        "ml_inference",
        "TagRepository",
        "SongTagRepository",
        "LibraryTagsDb",
        "TagRefRepository",
        "replace_song_tags",
        "replace_mood_tags",
        "save_mood_tags",
    ):
        assert all(forbidden not in token for token in tokens)
