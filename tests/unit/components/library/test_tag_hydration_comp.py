"""Tests for ``nomarr.components.library.tag_hydration_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.tag_hydration_comp import (
    extract_canonical_metadata,
    hydrate_song_with_metadata,
    hydrate_songs_with_metadata,
)


class TestExtractCanonicalMetadata:
    """Tests for ``extract_canonical_metadata()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_all_fields_present(self) -> None:
        tag_docs = [
            {"name": "artist", "value": ["Artist Name"]},
            {"name": "album", "value": ["Album Name"]},
            {"name": "title", "value": ["Song Title"]},
            {"name": "artists", "value": ["Artist A", "Artist B"]},
            {"name": "label", "value": ["Label Z", "Label A"]},
            {"name": "genre", "value": ["Rock", "Pop"]},
            {"name": "year", "value": ["2023"]},
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
            {"name": "artists", "value": ["Fallback Artist", "Other Artist"]},
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result["artist"] == "Fallback Artist"
        assert result["artists"] == ["Fallback Artist", "Other Artist"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_year_int_coercion(self) -> None:
        tag_docs = [{"name": "year", "value": ["2023"]}]

        result = extract_canonical_metadata(tag_docs)

        assert result["year"] == 2023
        assert isinstance(result["year"], int)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_year_parse_failure_returns_none(self) -> None:
        tag_docs = [{"name": "year", "value": ["not-a-year"]}]

        result = extract_canonical_metadata(tag_docs)

        assert result["year"] is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sorted_list_normalization(self) -> None:
        tag_docs = [
            {"name": "artists", "value": ["Z Artist", "A Artist", "M Artist"]},
            {"name": "label", "value": ["Z Label", "A Label"]},
            {"name": "genre", "value": ["Rock", "Electronic", "Ambient"]},
        ]

        result = extract_canonical_metadata(tag_docs)

        assert result["artists"] == ["A Artist", "M Artist", "Z Artist"]
        assert result["labels"] == ["A Label", "Z Label"]
        assert result["genres"] == ["Ambient", "Electronic", "Rock"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_partial_tags(self) -> None:
        tag_docs = [
            {"name": "artist", "value": ["Some Artist"]},
            {"name": "year", "value": ["1999"]},
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
        mock_db.library.list_file_tags_for_files.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_batch_reading_populates_all_docs(self) -> None:
        mock_db = MagicMock()
        file_docs = [
            {"_id": f"{'library_files'}/1", "path": "/music/song1.flac"},
            {"_id": f"{'library_files'}/2", "path": "/music/song2.flac"},
        ]
        mock_db.library.list_file_tags_for_files.return_value = {
            f"{'library_files'}/1": [
                {"name": "artist", "value": ["Artist One"]},
                {"name": "album", "value": ["Album One"]},
                {"name": "title", "value": ["Title One"]},
                {"name": "artists", "value": ["Artist One"]},
                {"name": "label", "value": ["Label One"]},
                {"name": "genre", "value": ["Rock"]},
                {"name": "year", "value": ["2020"]},
            ],
            f"{'library_files'}/2": [
                {"name": "artist", "value": ["Artist Two"]},
                {"name": "album", "value": ["Album Two"]},
                {"name": "title", "value": ["Title Two"]},
                {"name": "artists", "value": ["Artist Two"]},
                {"name": "label", "value": ["Label Two"]},
                {"name": "genre", "value": ["Pop"]},
                {"name": "year", "value": ["2021"]},
            ],
        }

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        mock_db.library.list_file_tags_for_files.assert_called_once_with(
            [f"{'library_files'}/1", f"{'library_files'}/2"]
        )
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
        file_docs = [{"_id": f"{'library_files'}/1", "path": "/music/song.flac"}]
        mock_db.library.list_file_tags_for_files.return_value = {
            f"{'library_files'}/1": [],
        }

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
        file_docs = [{"_id": f"{'library_files'}/1", "path": "/music/song.flac"}]
        mock_db.library.list_file_tags_for_files.return_value = {
            f"{'library_files'}/1": [
                {"name": "artist", "value": ["New Artist"]},
            ],
        }

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        assert "artist" not in file_docs[0]
        assert result[0]["artist"] == "New Artist"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_docs_without_string_id_returned_unchanged(self) -> None:
        mock_db = MagicMock()
        file_docs = [
            {"path": "/music/no_id.flac"},
            {"_id": 123, "path": "/music/int_id.flac"},
            {"_id": None, "path": "/music/none_id.flac"},
        ]

        result = hydrate_songs_with_metadata(mock_db, file_docs)

        mock_db.library.list_file_tags_for_files.assert_not_called()
        assert len(result) == 3
        assert result[0] == {"path": "/music/no_id.flac"}
        assert result[1] == {"_id": 123, "path": "/music/int_id.flac"}
        assert result[2] == {"_id": None, "path": "/music/none_id.flac"}
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
        file_doc = {"_id": f"{'library_files'}/1", "path": "/music/song.flac"}
        mock_db.library.list_file_tags_for_files.return_value = {
            f"{'library_files'}/1": [
                {"name": "artist", "value": ["Solo Artist"]},
                {"name": "album", "value": ["Solo Album"]},
                {"name": "title", "value": ["Solo Title"]},
                {"name": "artists", "value": ["Solo Artist"]},
                {"name": "label", "value": ["Solo Label"]},
                {"name": "genre", "value": ["Jazz"]},
                {"name": "year", "value": ["2022"]},
            ],
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
        mock_db.library.list_file_tags_for_files.assert_called_once_with([f"{'library_files'}/1"])
