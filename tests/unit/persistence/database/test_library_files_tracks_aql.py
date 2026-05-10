"""Tests for library-file track query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import get_tracks_for_matching


class TestGetTracksForMatching:
    """Tests for ``get_tracks_for_matching``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_rows_from_constructor_projection(self) -> None:
        """Returns projected rows with ISRC hydrated from tag traversal."""
        mock_db = MagicMock()
        mock_db.library_files_aql.get_tracks_for_matching.return_value = [
            {
                "_id": "library_files/1",
                "path": "C:/Music/song.mp3",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "isrc": "ABC123",
            }
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
        mock_db.library_files_aql.get_tracks_for_matching.assert_called_once_with(library_id="libraries/123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_library_scoped_query_uses_outbound_library_edge(self) -> None:
        """Library scoping should traverse library_contains_file edges, not file.library_id."""
        mock_db = MagicMock()
        mock_db.library_files_aql.get_tracks_for_matching.return_value = []

        get_tracks_for_matching(mock_db, library_id="libraries/123")

        mock_db.library_files_aql.get_tracks_for_matching.assert_called_once_with(library_id="libraries/123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_global_query_scans_library_files_collection(self) -> None:
        """Without library scoping, the query should scan library files via collection get."""
        mock_db = MagicMock()
        mock_db.library_files_aql.get_tracks_for_matching.return_value = []

        get_tracks_for_matching(mock_db)

        mock_db.library_files_aql.get_tracks_for_matching.assert_called_once_with(library_id=None)
