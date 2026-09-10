"""Tests for ``nomarr.components.library.tag_hydration_comp``.

These assert the typed hydration boundary: metadata-only ADR-045 mappings carried in
``HydratedSong`` (never merged into a song document), artist fallback, sorted list
fields, invalid-year warning (never raise), empty metadata for no-tag/missing/
unresolvable songs, and non-mutation of the semantic input ``Song``.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from nomarr.components.library.song_query_types import HydratedSong
from nomarr.components.library.tag_hydration_comp import (
    extract_canonical_metadata,
    hydrate_song_with_metadata,
    hydrate_songs_with_metadata,
)
from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment

CANONICAL_KEYS = {"artist", "album", "title", "artists", "labels", "genres", "year"}


def _assignment(name: str, value: object, namespace: str = "default") -> SongTagAssignment:
    return SongTagAssignment(name=name, value=value, namespace=namespace)


def _db(tags_by_identity: dict[SongIdentity, tuple[SongTagAssignment, ...]]) -> MagicMock:
    db = MagicMock()
    db.library.list_song_tags_for_songs.return_value = tags_by_identity
    return db


def _identity(song_state_contract, normalized_path: str) -> SongIdentity:
    lib = song_state_contract.make_library()
    return SongIdentity(library=lib, normalized_path=normalized_path)


# ─────────────────────────────────────────────────────────────────────────
# extract_canonical_metadata — ADR-045 derivation
# ─────────────────────────────────────────────────────────────────────────


class TestExtractCanonicalMetadata:
    @pytest.mark.unit
    def test_scalar_fields_take_first_value(self) -> None:
        tags = [
            _assignment("artist", "Artist A"),
            _assignment("artist", "Artist B"),
            _assignment("album", "Album"),
            _assignment("title", "Title"),
        ]
        out = extract_canonical_metadata(tags)
        assert out["artist"] == "Artist A"
        assert out["album"] == "Album"
        assert out["title"] == "Title"

    @pytest.mark.unit
    def test_artist_falls_back_to_first_artists_value(self) -> None:
        out = extract_canonical_metadata([_assignment("artists", "Fallback Artist")])
        assert out["artist"] == "Fallback Artist"

    @pytest.mark.unit
    def test_artist_is_none_when_no_artist_or_artists(self) -> None:
        out = extract_canonical_metadata([_assignment("album", "A")])
        assert out["artist"] is None

    @pytest.mark.unit
    def test_list_fields_sorted_case_preserved(self) -> None:
        tags = [
            _assignment("label", "z"),
            _assignment("label", "A"),
            _assignment("genre", "b"),
            _assignment("genre", "a"),
        ]
        out = extract_canonical_metadata(tags)
        assert out["labels"] == ["A", "z"]
        assert out["genres"] == ["a", "b"]
        assert out["artists"] is None

    @pytest.mark.unit
    def test_year_is_int_and_invalid_year_warns_returns_none(self, caplog) -> None:
        assert extract_canonical_metadata([_assignment("year", "2020")])["year"] == 2020
        with caplog.at_level(logging.WARNING):
            out = extract_canonical_metadata([_assignment("year", "not-a-year")])
        assert out["year"] is None
        assert any("Failed to parse year" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_non_string_values_stringified(self) -> None:
        out = extract_canonical_metadata([_assignment("artist", 123), _assignment("year", 1999)])
        assert out["artist"] == "123"
        assert out["year"] == 1999

    @pytest.mark.unit
    def test_empty_input_yields_all_none_keys(self) -> None:
        out = extract_canonical_metadata([])
        assert set(out) == CANONICAL_KEYS
        assert all(out[k] is None for k in CANONICAL_KEYS)


# ─────────────────────────────────────────────────────────────────────────
# hydrate_songs_with_metadata — typed carrier, no-tag/missing/unresolvable
# ─────────────────────────────────────────────────────────────────────────


class TestHydrateSongsWithMetadata:
    @pytest.mark.unit
    def test_empty_input_returns_empty_list(self, song_state_contract) -> None:
        db = _db({})
        assert hydrate_songs_with_metadata(db, [], []) == []

    @pytest.mark.unit
    def test_no_tags_yields_empty_metadata_mapping(self, song_state_contract) -> None:
        song = song_state_contract.make_song("a.flac")
        identity = _identity(song_state_contract, "a.flac")
        db = _db({identity: ()})
        result = hydrate_songs_with_metadata(db, [song], [identity])
        assert len(result) == 1
        hyd = result[0]
        assert isinstance(hyd, HydratedSong)
        assert hyd.song is song
        assert hyd.metadata == {}
        # metadata keys stay within the ADR-045 vocabulary even when populated
        assert set(hyd.metadata) <= CANONICAL_KEYS

    @pytest.mark.unit
    def test_unresolvable_locator_yields_empty_metadata(self, song_state_contract) -> None:
        song = song_state_contract.make_song("a.flac")
        identity = _identity(song_state_contract, "a.flac")
        # Facade returns nothing for this identity (omitted = unresolvable).
        db = _db({})
        hyd = hydrate_songs_with_metadata(db, [song], [identity])[0]
        assert hyd.song is song
        assert hyd.metadata == {}

    @pytest.mark.unit
    def test_metadata_is_derived_and_strips_none_values(self, song_state_contract) -> None:
        song = song_state_contract.make_song("a.flac")
        identity = _identity(song_state_contract, "a.flac")
        db = _db(
            {
                identity: (
                    _assignment("artist", "A"),
                    _assignment("album", "B"),
                    _assignment("genre", "rock"),
                )
            }
        )
        hyd = hydrate_songs_with_metadata(db, [song], [identity])[0]
        assert hyd.metadata == {"artist": "A", "album": "B", "genres": ["rock"]}
        assert set(hyd.metadata) <= CANONICAL_KEYS
        assert "year" not in hyd.metadata  # None keys omitted, never injected

    @pytest.mark.unit
    def test_batch_preserves_order_and_parallel_identity_mapping(self, song_state_contract) -> None:
        s1 = song_state_contract.make_song("a.flac")
        s2 = song_state_contract.make_song("b.flac")
        i1 = _identity(song_state_contract, "a.flac")
        i2 = _identity(song_state_contract, "b.flac")
        db = _db({i2: (_assignment("title", "B"),)})
        result = hydrate_songs_with_metadata(db, [s1, s2], [i1, i2])
        assert [r.song for r in result] == [s1, s2]
        assert result[0].metadata == {}
        assert result[1].metadata == {"title": "B"}

    @pytest.mark.unit
    def test_does_not_mutate_input_song(self, song_state_contract) -> None:
        song = song_state_contract.make_song("a.flac", tagged=False)
        identity = _identity(song_state_contract, "a.flac")
        db = _db({identity: (_assignment("artist", "A"),)})
        hydrate_songs_with_metadata(db, [song], [identity])
        assert song.tagged is False
        assert not hasattr(song, "song_id")
        assert not hasattr(song, "library_id")

    @pytest.mark.unit
    def test_hydrate_song_with_metadata_wrapper(self, song_state_contract) -> None:
        song = song_state_contract.make_song("a.flac")
        identity = _identity(song_state_contract, "a.flac")
        db = _db({identity: (_assignment("artist", "A"),)})
        hyd = hydrate_song_with_metadata(db, song, identity)
        assert isinstance(hyd, HydratedSong)
        assert hyd.song is song
        assert hyd.metadata == {"artist": "A"}
