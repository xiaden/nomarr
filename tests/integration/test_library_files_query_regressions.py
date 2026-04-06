"""Regression tests for ``nomarr.persistence.database.library_files_aql.queries``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_files_aql.queries import LibraryFilesQueriesMixin


class _ConcreteQueriesMixin(LibraryFilesQueriesMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.collection = MagicMock()
        self.parent_db = None


class TestLibraryFilesQueryRegressions:
    """Regression coverage for Phase 1 AQL fixes."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_search_results_include_edge_derived_library_id_without_changing_count_query(self) -> None:
        """Search data query should hydrate ``library_id`` from edges while count stays filter-only."""
        mock_db = MagicMock()
        mock_db.aql.execute.side_effect = [
            iter([1]),
            iter(
                [
                    {
                        "_id": "library_files/1",
                        "path": "D:/Music/Test Song.flac",
                        "normalized_path": "Test Song.flac",
                        "artist": "Test Artist",
                        "album": "Test Album",
                        "title": "Test Song",
                        "tags": [],
                        "library_id": "libraries/1",
                    },
                ],
            ),
        ]
        mixin = _ConcreteQueriesMixin(mock_db)

        files, total = mixin.search_library_files_with_tags(query_text="Test Song")

        assert total == 1
        assert files[0]["library_id"] == "libraries/1"

        count_query = mock_db.aql.execute.call_args_list[0].args[0]
        data_query = mock_db.aql.execute.call_args_list[1].args[0]
        data_bind_vars = mock_db.aql.execute.call_args_list[1].kwargs["bind_vars"]

        assert "library_contains_file" not in count_query
        assert (
            "LET lib_id = FIRST(FOR lib IN INBOUND file._id library_contains_file LIMIT 1 RETURN lib._id)" in data_query
        )
        assert "RETURN MERGE(file, { tags: tags, library_id: lib_id })" in data_query
        assert data_bind_vars["q_pattern"] == "%Test Song%"
        assert data_bind_vars["limit"] == 100
        assert data_bind_vars["offset"] == 0


class TestGetRecentlyProcessed:
    """Regression coverage for ``get_recently_processed`` query variants."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_returns_scanned_at_field(self) -> None:
        """Recently processed query should return the scanned_at field."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter(
            [
                {
                    "file_id": "library_files/1",
                    "path": "Artist/Album/Test Song.flac",
                    "title": "Test Song",
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "scanned_at": 1_710_000_000,
                },
            ],
        )
        mixin = _ConcreteQueriesMixin(mock_db)

        rows = mixin.get_recently_processed(limit=5)

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert rows[0]["scanned_at"] == 1_710_000_000
        assert bind_vars["limit"] == 5

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_library_scoped_binds_library_id(self) -> None:
        """Library-scoped query should pass library_id as a bind variable."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteQueriesMixin(mock_db)

        mixin.get_recently_processed(library_id="libraries/123")

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert bind_vars["library_id"] == "libraries/123"

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_global_query_omits_library_id_bind(self) -> None:
        """Global query should not bind a library_id."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteQueriesMixin(mock_db)

        mixin.get_recently_processed()

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert "library_id" not in bind_vars
