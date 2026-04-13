"""Tests for ``nomarr.components.ml.vectors.ml_vector_retrieve_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import get_cold_track_vector


@pytest.mark.unit
class TestGetColdTrackVector:
    """Tests for ``get_cold_track_vector``."""

    def test_returns_none_when_cold_count_zero(self) -> None:
        """Returns None without fetching cold ops when cold_count is 0."""
        mock_db = MagicMock()
        mock_db.get_vectors_track_maintenance.return_value.get_stats.return_value = {
            "cold_count": 0,
            "hot_count": 5,
        }

        result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result is None
        mock_db.get_vectors_track_cold.assert_not_called()

    def test_returns_none_when_cold_count_negative(self) -> None:
        """Returns None when cold_count is a negative value (string from stats)."""
        mock_db = MagicMock()
        mock_db.get_vectors_track_maintenance.return_value.get_stats.return_value = {
            "cold_count": "-1",
            "hot_count": 0,
        }

        result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result is None
        mock_db.get_vectors_track_cold.assert_not_called()

    def test_returns_vector_document_when_cold_exists(self) -> None:
        """Fetches and returns vector from cold collection when cold_count > 0."""
        mock_db = MagicMock()
        expected_doc = {
            "_id": "vectors_track_cold__effnet__lib1/k1",
            "_key": "k1",
            "file_id": "library_files/f1",
            "vector_n": [0.1, 0.2, 0.3],
            "score": 0.95,
        }
        mock_db.get_vectors_track_maintenance.return_value.get_stats.return_value = {
            "cold_count": 42,
            "hot_count": 0,
        }
        mock_db.get_vectors_track_cold.return_value.get_vector.return_value = expected_doc

        result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result == expected_doc
        mock_db.get_vectors_track_maintenance.assert_called_once_with("effnet", "lib1")
        mock_db.get_vectors_track_cold.assert_called_once_with("effnet", "lib1")
        mock_db.get_vectors_track_cold.return_value.get_vector.assert_called_once_with("library_files/f1")

    def test_returns_none_when_vector_not_found_in_cold(self) -> None:
        """Returns None when cold collection exists but track has no vector."""
        mock_db = MagicMock()
        mock_db.get_vectors_track_maintenance.return_value.get_stats.return_value = {
            "cold_count": 10,
            "hot_count": 0,
        }
        mock_db.get_vectors_track_cold.return_value.get_vector.return_value = None

        result = get_cold_track_vector(mock_db, "library_files/missing", "effnet", "lib1")

        assert result is None
