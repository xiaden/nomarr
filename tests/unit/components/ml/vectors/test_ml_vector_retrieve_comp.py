"""Tests for ``nomarr.components.ml.vectors.ml_vector_retrieve_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    get_cold_track_vector,
    search_similar_cold_track_vectors,
)


def _make_db() -> MagicMock:
    """Create a mock Database with sync ml methods configured."""
    db = MagicMock()
    db.ml.get_embedding_stats = MagicMock()
    db.ml.list_song_vectors = MagicMock()
    db.ml.search_vectors = MagicMock()
    return db


@pytest.mark.unit
class TestGetColdTrackVector:
    """Tests for ``get_cold_track_vector``."""

    def test_returns_none_when_cold_count_zero(self) -> None:
        """Returns None without fetching vectors when cold_count is 0."""
        mock_db = _make_db()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 0,
            "hot_count": 5,
            "index_exists": False,
        }

        result = get_cold_track_vector(mock_db, 1, "effnet")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.list_song_vectors.assert_not_called()

    def test_returns_none_when_cold_count_negative(self) -> None:
        """Returns None when cold_count is a negative/string value from stats."""
        mock_db = _make_db()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": "-1",
            "hot_count": 0,
            "index_exists": False,
        }

        result = get_cold_track_vector(mock_db, 2, "effnet")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.list_song_vectors.assert_not_called()

    def test_returns_vector_document_when_cold_exists(self) -> None:
        """Fetches and returns vector via list_song_vectors when cold_count > 0."""
        mock_db = _make_db()
        expected_doc = {
            "song_id": 1,
            "vector": [0.1, 0.2, 0.3],
            "score": 0.95,
        }
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 42,
            "hot_count": 0,
            "index_exists": True,
        }
        mock_db.ml.list_song_vectors.return_value = [expected_doc]

        result = get_cold_track_vector(mock_db, 1, "effnet")

        assert result == expected_doc
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.list_song_vectors.assert_called_once_with("effnet", 1)

    def test_returns_none_when_vector_not_found(self) -> None:
        """Returns None when cold collection has docs but file has no vector."""
        mock_db = _make_db()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 10,
            "hot_count": 0,
            "index_exists": True,
        }
        mock_db.ml.list_song_vectors.return_value = []

        result = get_cold_track_vector(mock_db, 999, "effnet")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.list_song_vectors.assert_called_once_with("effnet", 999)


@pytest.mark.unit
class TestSearchSimilarColdTrackVectors:
    """Tests for ``search_similar_cold_track_vectors``."""

    def test_returns_empty_when_cold_collection_is_empty(self) -> None:
        """Skips ANN search when the cold collection has no promoted vectors."""
        mock_db = _make_db()
        mock_db.ml.get_embedding_stats.return_value = {"cold_count": 0}

        result = search_similar_cold_track_vectors(
            mock_db,
            backbone_id="effnet",
            seed_vector=[0.1, 0.2, 0.3],
            result_limit=11,
        )

        assert result == []
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.search_vectors.assert_not_called()

    def test_queries_search_vectors_when_cold_has_content(self) -> None:
        """Delegates to db.ml.search_vectors when cold_count > 0."""
        mock_db = _make_db()
        mock_db.ml.get_embedding_stats.return_value = {"cold_count": 300}
        mock_db.ml.search_vectors.return_value = [{"song_id": 2, "score": 0.91}]

        result = search_similar_cold_track_vectors(
            mock_db,
            backbone_id="effnet",
            seed_vector=[0.1, 0.2, 0.3],
            result_limit=11,
        )

        assert result == [{"song_id": 2, "score": 0.91}]
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_db.ml.search_vectors.assert_called_once_with(
            "effnet",
            [0.1, 0.2, 0.3],
            limit=11,
        )
