"""Tests for ``nomarr.persistence.database.library_files_aql.tracks``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_files_aql.tracks import LibraryFilesTracksMixin


class _ConcreteTracksMixin(LibraryFilesTracksMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.collection = MagicMock()
        self.parent_db = None


class TestGetTracksForMatching:
    """Tests for ``LibraryFilesTracksMixin.get_tracks_for_matching``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_rows_from_cursor(self) -> None:
        """Returns the AQL rows unchanged."""
        mock_db = MagicMock()
        expected = [
            {
                "_id": "library_files/1",
                "path": "C:/Music/song.mp3",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "isrc": "ABC123",
            }
        ]
        mock_db.aql.execute.return_value = iter(expected)
        mixin = _ConcreteTracksMixin(mock_db)

        result = mixin.get_tracks_for_matching(library_id="libraries/123")

        assert result == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_library_scoped_query_uses_outbound_library_edge(self) -> None:
        """Library scoping should traverse library_contains_file edges, not file.library_id."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteTracksMixin(mock_db)

        mixin.get_tracks_for_matching(library_id="libraries/123")

        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert "FOR f IN OUTBOUND @library_id library_contains_file" in query
        assert "FILTER f.is_valid == true" in query
        assert "FILTER f.library_id == @library_id" not in query
        assert bind_vars["library_id"] == "libraries/123"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_global_query_scans_library_files_collection(self) -> None:
        """Without library scoping, the query should keep scanning library_files directly."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteTracksMixin(mock_db)

        mixin.get_tracks_for_matching()

        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert "FOR f IN library_files" in query
        assert "OUTBOUND @library_id library_contains_file" not in query
        assert bind_vars == {}
