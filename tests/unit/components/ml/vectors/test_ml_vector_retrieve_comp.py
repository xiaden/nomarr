"""Tests for ``nomarr.components.ml.vectors.ml_vector_retrieve_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    get_cold_track_vector,
    search_similar_cold_track_vectors,
)

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_retrieve_comp"


@pytest.mark.unit
class TestGetColdTrackVector:
    """Tests for ``get_cold_track_vector``."""

    def test_returns_none_when_cold_count_zero(self) -> None:
        """Returns None without fetching cold ops when cold_count is 0."""
        mock_db = MagicMock()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 0,
            "hot_count": 5,
            "index_exists": False,
        }

        with patch(f"{PATCH_BASE}.get_cold_namespace") as mock_get_cold:
            result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_get_cold.assert_not_called()

    def test_returns_none_when_cold_count_negative(self) -> None:
        """Returns None when cold_count is a negative value (string from stats)."""
        mock_db = MagicMock()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": "-1",
            "hot_count": 0,
            "index_exists": False,
        }

        with patch(f"{PATCH_BASE}.get_cold_namespace") as mock_get_cold:
            result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_get_cold.assert_not_called()

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
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 42,
            "hot_count": 0,
            "index_exists": True,
        }
        cold_ops = MagicMock()
        cold_ops.get_vector.return_value = expected_doc

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = get_cold_track_vector(mock_db, "library_files/f1", "effnet", "lib1")

        assert result == expected_doc
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_get_cold.assert_called_once_with(mock_db, "effnet", "lib1")
        cold_ops.get_vector.assert_called_once_with("library_files/f1")

    def test_returns_none_when_vector_not_found_in_cold(self) -> None:
        """Returns None when cold collection exists but track has no vector."""
        mock_db = MagicMock()
        mock_db.ml.get_embedding_stats.return_value = {
            "cold_count": 10,
            "hot_count": 0,
            "index_exists": True,
        }
        cold_ops = MagicMock()
        cold_ops.get_vector.return_value = None

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = get_cold_track_vector(mock_db, "library_files/missing", "effnet", "lib1")

        assert result is None
        mock_db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_get_cold.assert_called_once_with(mock_db, "effnet", "lib1")
        cold_ops.get_vector.assert_called_once_with("library_files/missing")


@pytest.mark.unit
class TestSearchSimilarColdTrackVectors:
    """Tests for ``search_similar_cold_track_vectors``."""

    def test_returns_empty_when_cold_collection_is_empty(self) -> None:
        """Skips ANN search when the cold collection has no promoted vectors."""
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 0

        with (
            patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold,
            patch(f"{PATCH_BASE}.compute_nlists") as mock_compute_nlists,
            patch(f"{PATCH_BASE}.compute_nprobe") as mock_compute_nprobe,
        ):
            result = search_similar_cold_track_vectors(
                mock_db,
                backbone_id="effnet",
                library_key="lib1",
                seed_vector=[0.1, 0.2, 0.3],
                result_limit=11,
                vector_group_size=15,
                vector_search_thoroughness=10,
            )

        assert result == []
        mock_get_cold.assert_called_once_with(mock_db, "effnet", "lib1")
        mock_compute_nlists.assert_not_called()
        mock_compute_nprobe.assert_not_called()
        cold_ops.get.assert_not_called()
        cold_ops.ann_search.assert_not_called()

    def test_computes_nprobe_and_executes_ann_search(self) -> None:
        """Uses cold count to size ANN probing before delegating to persistence."""
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 300
        cold_ops.ann_search.return_value = [{"file_id": "library_files/2", "score": 0.91}]

        with (
            patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold,
            patch(f"{PATCH_BASE}.compute_nlists", return_value=20) as mock_compute_nlists,
            patch(f"{PATCH_BASE}.compute_nprobe", return_value=7) as mock_compute_nprobe,
        ):
            result = search_similar_cold_track_vectors(
                mock_db,
                backbone_id="effnet",
                library_key="lib1",
                seed_vector=[0.1, 0.2, 0.3],
                result_limit=11,
                vector_group_size=15,
                vector_search_thoroughness=25,
            )

        assert result == [{"file_id": "library_files/2", "score": 0.91}]
        mock_get_cold.assert_called_once_with(mock_db, "effnet", "lib1")
        mock_compute_nlists.assert_called_once_with(300, 15)
        mock_compute_nprobe.assert_called_once_with(20, 25)
        cold_ops.get.assert_not_called()
        cold_ops.ann_search.assert_called_once_with([0.1, 0.2, 0.3], 11, nprobe=7)
