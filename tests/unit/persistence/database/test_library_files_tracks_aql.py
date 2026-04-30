"""Tests for library-file track query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import get_tracks_for_matching


class TestGetTracksForMatching:
    """Tests for ``LibraryFilesTracksMixin.get_tracks_for_matching``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_rows_from_constructor_projection(self) -> None:
        """Returns projected rows with ISRC hydrated from tag traversal."""
        mock_db = MagicMock()
        mock_db.libraries.traversal.return_value = [
            {
                "_id": "library_files/1",
                "path": "C:/Music/song.mp3",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "is_valid": True,
            }
        ]
        mock_db.library_files.traversal.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"rel": "isrc", "value": "ABC123"}}
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

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_library_scoped_query_uses_outbound_library_edge(self) -> None:
        """Library scoping should traverse library_contains_file edges, not file.library_id."""
        mock_db = MagicMock()
        mock_db.libraries.traversal.return_value = []

        get_tracks_for_matching(mock_db, library_id="libraries/123")

        mock_db.libraries.traversal.assert_called_once_with("libraries/123", "library_contains_file", limit=1000)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_global_query_scans_library_files_collection(self) -> None:
        """Without library scoping, the query should scan library files via by_filter."""
        mock_db = MagicMock()
        mock_db.library_files.get.many.by_filter.return_value = []

        get_tracks_for_matching(mock_db)

        mock_db.library_files.get.many.by_filter.assert_called_once_with({"is_valid": True}, limit=1000)
