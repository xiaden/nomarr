"""Tests for library-file track query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import get_tracks_for_matching
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT


class TestGetTracksForMatching:
    """Tests for ``get_tracks_for_matching``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_rows_from_constructor_projection(self) -> None:
        """Returns projected rows with ISRC hydrated from tag traversal."""
        mock_db = MagicMock()
        mock_db.libraries.library_contains_file.return_value = [
            {
                "_id": "library_files/1",
                "path": "C:/Music/song.mp3",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "is_valid": True,
            }
        ]
        mock_db.library_files.song_has_tags.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"name": "isrc", "value": "ABC123"}}
        ]

        result = get_tracks_for_matching(mock_db, library_id="libraries/123")

        assert result == [
            {
                "_id": "library_files/1",
                "path": "C:/Music/song.mp3",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "isrc": "ABC123",
            }
        ]
        mock_db.libraries.library_contains_file.assert_called_once_with("libraries/123", limit=DEFAULT_LIMIT)
        mock_db.library_files.song_has_tags.by_ids.assert_called_once_with(["library_files/1"], name="isrc")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_library_scoped_query_uses_outbound_library_edge(self) -> None:
        """Library scoping should traverse library_contains_file edges, not file.library_id."""
        mock_db = MagicMock()
        mock_db.libraries.library_contains_file.return_value = []

        get_tracks_for_matching(mock_db, library_id="libraries/123")

        mock_db.libraries.library_contains_file.assert_called_once_with("libraries/123", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_global_query_scans_library_files_collection(self) -> None:
        """Without library scoping, the query should scan library files via collection get."""
        mock_db = MagicMock()
        mock_db.library_files.get.return_value = []

        get_tracks_for_matching(mock_db)

        mock_db.library_files.get.assert_called_once_with(is_valid=True, limit=DEFAULT_LIMIT)
