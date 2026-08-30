"""Tests for ``nomarr.components.library.tag_hydration_comp``."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.components.library.tag_hydration_comp import (
    extract_canonical_metadata,
    hydrate_song_with_metadata,
    hydrate_songs_with_metadata,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment


def _identity(song_id: int) -> SongIdentity:
    """Build a domain ``SongIdentity`` for a numeric song handle."""
    return SongIdentity(
        library=LibraryIdentity(name="main", root_path="/music"),
        normalized_path=f"song{song_id}.flac",
    )


def _assign(name: str, value: str | int | float | bool) -> SongTagAssignment:
    """Build a domain ``SongTagAssignment`` (scalar value) for one song."""
    return SongTagAssignment(name=name, value=value, namespace="")


class TestExtractCanonicalMetadata:
    """Tests for ``extract_canonical_metadata()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_all_fields_present(self) -> None:
        tag_docs = [
            _assign("artist", "Artist Name"),
            _assign("album", "Album Name"),
            _assign("title", "Song Title"),
            _assign("artists", "Artist A"),
            _assign("artists", "Artist B"),
            _assign("label", "Label Z"),
            _assign("label", "Label A"),
            _assign("genre", "Rock"),
            _assign("genre", "Pop"),
            _assign("year", "2023"),
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result == {
            "artist": "Artist Name",
            "album": "Album Name",
            "title": "Song Title",
            "artists": ["Artist A", "Artist B"],
            "labels": ["Label A", "Label Z"],
            "genres": ["Pop", "Rock"],
            "year": 2023,
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_missing_tags_return_none(self) -> None:
        result = extract_canonical_metadata([])

        assert result == {
            "artist": None,
            "album": None,
            "title": None,
            "artists": None,
            "labels": None,
            "genres": None,
            "year": None,
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_artist_fallback_to_artists_tag(self) -> None:
        tag_docs = [
            _assign("artists", "Fallback Artist"),
            _assign("artists", "Other Artist"),
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result["artist"] == "Fallback Artist"
        assert result["artists"] == ["Fallback Artist", "Other Artist"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_year_int_coercion(self) -> None:
        tag_docs = [_assign("year", "2023")]

        result = extract_canonical_metadata(tag_docs)

        assert result["year"] == 2023
        assert isinstance(result["year"], int)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_year_parse_failure_returns_none(self) -> None:
        tag_docs = [_assign("year", "not-a-year")]

        result = extract_canonical_metadata(tag_docs)

        assert result["year"] is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sorted_list_normalization(self) -> None:
        tag_docs = [
            _assign("artists", "Z Artist"),
            _assign("artists", "A Artist"),
            _assign("artists", "M Artist"),
            _assign("label", "Z Label"),
            _assign("label", "A Label"),
            _assign("genre", "Rock"),
            _assign("genre", "Electronic"),
            _assign("genre", "Ambient"),
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result["artists"] == ["A Artist", "M Artist", "Z Artist"]
        assert result["labels"] == ["A Label", "Z Label"]
        assert result["genres"] == ["Ambient", "Electronic", "Rock"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_partial_tags(self) -> None:
        tag_docs = [
            _assign("artist", "Some Artist"),
            _assign("year", "1999"),
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result["artist"] == "Some Artist"
        assert result["year"] == 1999
        assert result["album"] is None
        assert result["title"] is None
        assert result["artists"] is None
        assert result["labels"] is None
        assert result["genres"] is None


class TestHydrateFileDocsWithMetadata:
    """Tests for ``hydrate_songs_with_metadata()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_input(self) -> None:
        mock_db = MagicMock()

        result = hydrate_songs_with_metadata(mock_db, [])

        assert result == []
        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_batch_reading_populates_all_docs(self) -> None:
        mock_db = MagicMock()
        file_docs = [
            {"id": 1, "path": "/music/song1.flac"},
            {"id": 2, "path": "/music/song2.flac"},
        ]
        ident1 = _identity(1)
        ident2 = _identity(2)
        mock_db.library.resolve_song_identities.return_value = {1: ident1, 2: ident2}
        mock_db.library.list_song_tags_for_songs.return_value = {
            ident1: (
                _assign("artist", "Artist One"),
                _assign("album", "Album One"),
                _assign("title", "Title One"),
                _assign("artists", "Artist One"),
                _assign("label", "Label One"),
                _assign("genre", "Rock"),
                _assign("year", "2020"),
            ),
            ident2: (
                _assign("artist", "Artist Two"),
                _assign("album", "Album Two"),
                _assign("title", "Title Two"),
                _assign("artists", "Artist Two"),
                _assign("label", "Label Two"),
                _assign("genre", "Pop"),
                _assign("year", "2021"),
            ),
        }

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        mock_db.library.resolve_song_identities.assert_called_once_with([1, 2])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([ident1, ident2])
        assert len(result) == 2
        assert result[0]["artist"] == "Artist One"
        assert result[0]["album"] == "Album One"
        assert result[0]["title"] == "Title One"
        assert result[0]["year"] == 2020
        assert result[0]["path"] == "/music/song1.flac"
        assert result[1]["artist"] == "Artist Two"
        assert result[1]["album"] == "Album Two"
        assert result[1]["title"] == "Title Two"
        assert result[1]["year"] == 2021
        assert result[1]["path"] == "/music/song2.flac"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_file_with_no_tags_gets_none_fields(self) -> None:
        mock_db = MagicMock()
        file_docs = [{"id": 1, "path": "/music/song.flac"}]
        ident = _identity(1)
        mock_db.library.resolve_song_identities.return_value = {1: ident}
        mock_db.library.list_song_tags_for_songs.return_value = {ident: ()}

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        assert len(result) == 1
        # None values are stripped before merging — fields are absent unless
        # the underlying song doc carried them.
        assert result[0].get("artist") is None
        assert result[0].get("album") is None
        assert result[0].get("title") is None
        assert result[0].get("artists") is None
        assert result[0].get("labels") is None
        assert result[0].get("genres") is None
        assert result[0].get("year") is None
        assert result[0]["path"] == "/music/song.flac"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_original_docs_not_mutated(self) -> None:
        mock_db = MagicMock()
        file_docs = [{"id": 1, "path": "/music/song.flac"}]
        ident = _identity(1)
        mock_db.library.resolve_song_identities.return_value = {1: ident}
        mock_db.library.list_song_tags_for_songs.return_value = {
            ident: (_assign("artist", "New Artist"),),
        }

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        assert "artist" not in file_docs[0]
        assert result[0]["artist"] == "New Artist"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_docs_without_string_id_returned_unchanged(self) -> None:
        mock_db = MagicMock()
        file_docs: list[dict[str, Any]] = [
            {"path": "/music/no_id.flac"},
            {"id": 123, "path": "/music/int_id.flac"},
            {"id": None, "path": "/music/none_id.flac"},
        ]

        # Mock resolve_song_identities to resolve the valid id only.
        mock_db.library.resolve_song_identities.return_value = {123: _identity(123)}
        mock_db.library.list_song_tags_for_songs.return_value = {}

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        # Doc with id=123 triggers tag lookup; docs with missing or None id don't
        mock_db.library.resolve_song_identities.assert_called_once_with([123])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([_identity(123)])
        assert len(result) == 3
        assert result[0] == {"path": "/music/no_id.flac"}
        assert "id" in result[1] and result[1]["id"] == 123
        assert result[1]["path"] == "/music/int_id.flac"
        assert result[2] == {"id": None, "path": "/music/none_id.flac"}
        # Verify they are copies, not the same objects
        assert result[0] is not file_docs[0]
        assert result[1] is not file_docs[1]
        assert result[2] is not file_docs[2]


class TestHydrateFileDocWithMetadata:
    """Tests for ``hydrate_song_with_metadata()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_single_file_hydration(self) -> None:
        mock_db = MagicMock()
        file_doc = {"id": 1, "path": "/music/song.flac"}
        ident = _identity(1)
        mock_db.library.resolve_song_identities.return_value = {1: ident}
        mock_db.library.list_song_tags_for_songs.return_value = {
            ident: (
                _assign("artist", "Solo Artist"),
                _assign("album", "Solo Album"),
                _assign("title", "Solo Title"),
                _assign("artists", "Solo Artist"),
                _assign("label", "Solo Label"),
                _assign("genre", "Jazz"),
                _assign("year", "2022"),
            ),
        }

        result = hydrate_song_with_metadata(mock_db, file_doc)

        assert result["artist"] == "Solo Artist"
        assert result["album"] == "Solo Album"
        assert result["title"] == "Solo Title"
        assert result["artists"] == ["Solo Artist"]
        assert result["labels"] == ["Solo Label"]
        assert result["genres"] == ["Jazz"]
        assert result["year"] == 2022
        assert result["path"] == "/music/song.flac"
        mock_db.library.resolve_song_identities.assert_called_once_with([1])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([ident])
