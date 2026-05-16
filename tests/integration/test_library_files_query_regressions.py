"""Regression tests for library-file query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import get_recently_processed, search_library_files_with_tags


class TestLibraryFilesQueryRegressions:
    """Regression coverage for Phase 1 AQL fixes."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_search_results_include_edge_derived_library_id_after_constructor_migration(self) -> None:
        """Search results should still hydrate ``library_id`` via ownership edges."""
        file_doc = {
            "_id": "library_files/1",
            "path": "D:/Music/Test Song.flac",
            "normalized_path": "Test Song.flac",
            "artist": "Test Artist",
            "album": "Test Album",
            "title": "Test Song",
            "library_key": "1",
        }
        mock_db = MagicMock()
        # query_text-only search: title via search_files_by_text, artist/album via search_files_by_tag_pattern
        mock_db.library.search_files_by_text.return_value = []
        mock_db.library.search_files_by_tag_pattern.side_effect = [[], [file_doc]]
        # hydration: fetch by ids, then tags + library ownership
        mock_db.library.list_files_by_ids.return_value = [file_doc]
        mock_db.library.list_file_tags_for_files.return_value = {"library_files/1": []}
        mock_db.library.get_library_ids_for_files.return_value = {"library_files/1": "libraries/1"}

        files, total = search_library_files_with_tags(mock_db, query_text="Test Song")

        assert total == 1
        assert files[0]["library_id"] == "libraries/1"
        mock_db.library.list_file_tags_for_files.assert_called_once_with(["library_files/1"])


class TestGetRecentlyProcessed:
    """Regression coverage for ``get_recently_processed`` query variants."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_returns_scanned_at_field(self) -> None:
        """Recently processed query should return the scanned_at field."""
        mock_db = MagicMock()
        mock_db.app.list_file_docs_in_state.return_value = [
            {
                "_id": "library_files/1",
                "normalized_path": "Artist/Album/Test Song.flac",
                "title": "Test Song",
                "artist": "Test Artist",
                "album": "Test Album",
                "scanned_at": 1_710_000_000,
            },
        ]
        rows = get_recently_processed(mock_db, limit=5)

        assert rows[0]["activity_at"] == 1_710_000_000
        assert rows[0]["activity_event"] == "scanned"

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_library_scoped_intersects_tagged_files_with_library_edges(self) -> None:
        """Library-scoped query should intersect tagged files with ownership edges."""
        mock_db = MagicMock()
        mock_db.app.list_file_docs_in_state.return_value = [
            {"_id": "library_files/1", "normalized_path": "one.flac", "scanned_at": 10},
            {"_id": "library_files/2", "normalized_path": "two.flac", "scanned_at": 20},
        ]
        # Only library_files/2 belongs to the library
        mock_db.library.list_library_file_ids.return_value = ["library_files/2"]

        rows = get_recently_processed(mock_db, library_id="libraries/123")

        assert [row["file_id"] for row in rows] == ["library_files/2"]
        mock_db.library.list_library_file_ids.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_global_query_skips_library_edge_lookup(self) -> None:
        """Global query should not query library ownership edges."""
        mock_db = MagicMock()
        mock_db.app.list_file_docs_in_state.return_value = []

        get_recently_processed(mock_db)

        mock_db.library.list_library_file_ids.assert_not_called()
