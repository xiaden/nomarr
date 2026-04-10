"""Tests for nomarr.persistence.database.library_files_aql.crud update methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_files_aql.crud import LibraryFilesCrudMixin


class _ConcreteCrudMixin(LibraryFilesCrudMixin):
    """Minimal concrete class for testing the CRUD mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.collection = MagicMock()
        self.parent_db = None


class TestUpdateMetadataCache:
    """Tests for update_metadata_cache()."""

    @pytest.mark.unit
    def test_calls_aql_execute_with_correct_bind_vars(self) -> None:
        """Passes all metadata fields through bind_vars for one song."""
        mock_db = MagicMock()
        mixin = _ConcreteCrudMixin(mock_db)

        mixin.update_metadata_cache(
            "library_files/123",
            artist="Artist",
            artists=["Artist"],
            album="Album",
            labels=None,
            genres=["Rock"],
            year=2020,
        )

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert bind_vars == {
            "song_id": "library_files/123",
            "artist": "Artist",
            "artists": ["Artist"],
            "album": "Album",
            "labels": None,
            "genres": ["Rock"],
            "year": 2020,
        }


class TestUpdateMetadataCacheBatch:
    """Tests for update_metadata_cache_batch()."""

    @pytest.mark.unit
    def test_skips_aql_when_updates_empty(self) -> None:
        """Skips AQL entirely when there are no batch updates."""
        mock_db = MagicMock()
        mixin = _ConcreteCrudMixin(mock_db)

        mixin.update_metadata_cache_batch([])

        mock_db.aql.execute.assert_not_called()

    @pytest.mark.unit
    def test_calls_aql_with_updates_list(self) -> None:
        """Passes the full updates list through bind_vars."""
        mock_db = MagicMock()
        mixin = _ConcreteCrudMixin(mock_db)
        updates = [
            {
                "song_id": "library_files/1",
                "artist": "Artist 1",
                "artists": ["Artist 1"],
                "album": "Album 1",
                "labels": ["Label 1"],
                "genres": ["Rock"],
                "year": 2020,
            },
            {
                "song_id": "library_files/2",
                "artist": "Artist 2",
                "artists": ["Artist 2"],
                "album": "Album 2",
                "labels": ["Label 2"],
                "genres": ["Jazz"],
                "year": 2021,
            },
        ]

        mixin.update_metadata_cache_batch(updates)

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert bind_vars == {"updates": updates}
