"""Unit tests for ml_vector_idle_promotion_comp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

ML_IDLE_PROMOTION_MODULE = "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp"


@pytest.mark.unit
class TestListHotVectorTargets:
    """Tests for list_hot_vector_targets."""

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    def test_returns_pairs_with_hot_vectors(self, mock_discover: MagicMock) -> None:
        """Returns (backbone, library) pairs where hot count > 0."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet", "musicnn"]

        db = MagicMock()
        libraries = [
            {"_key": "lib1"},
            {"_key": "lib2"},
        ]

        # effnet__lib1 has vectors, effnet__lib2 has no hot collection,
        # musicnn__lib1 exists but empty, musicnn__lib2 has vectors.
        hot_ops_map: dict[str, int | None] = {
            "effnet__lib1": 42,
            "effnet__lib2": None,
            "musicnn__lib1": 0,
            "musicnn__lib2": 10,
        }

        def get_embedding_stats(backbone_id: str, library_key: str) -> dict:
            hot_count = hot_ops_map.get(f"{backbone_id}__{library_key}")
            return {
                "hot_count": 0 if hot_count is None else hot_count,
                "cold_count": 0,
                "index_exists": False,
            }

        db.ml.get_embedding_stats.side_effect = get_embedding_stats

        with patch(
            f"{ML_IDLE_PROMOTION_MODULE}.list_library_records",
            return_value=libraries,
        ):
            result = list_hot_vector_targets(db, "/models")

        assert result == [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_discover.assert_called_once_with("/models")

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    def test_returns_empty_when_no_backbones(self, mock_discover: MagicMock) -> None:
        """Returns empty list when no backbones discovered."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = []
        db = MagicMock()

        result = list_hot_vector_targets(db, "/models")

        assert result == []
        db.ml.get_embedding_stats.assert_not_called()

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    def test_returns_empty_when_no_libraries(self, mock_discover: MagicMock) -> None:
        """Returns empty list when no libraries exist."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet"]
        db = MagicMock()
        with patch(
            f"{ML_IDLE_PROMOTION_MODULE}.list_library_records",
            return_value=[],
        ):
            result = list_hot_vector_targets(db, "/models")

        assert result == []
        db.ml.get_embedding_stats.assert_not_called()


@pytest.mark.unit
class TestComputePromotionNlists:
    """Tests for ``compute_promotion_nlists``."""

    @pytest.mark.mocked
    def test_uses_library_group_size_when_available(self) -> None:
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import compute_promotion_nlists

        db = MagicMock()
        db.ml.get_embedding_stats.return_value = {
            "hot_count": 100,
            "cold_count": 200,
            "index_exists": False,
        }

        with (
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.get_library_record",
                return_value={"vector_group_size": 20},
            ),
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.compute_nlists",
                return_value=37,
            ) as mock_compute_nlists,
        ):
            result = compute_promotion_nlists(db, "effnet", "lib1")

        assert result == 37
        db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_compute_nlists.assert_called_once_with(300, 20)

    @pytest.mark.mocked
    def test_falls_back_to_default_group_size_when_library_missing(self) -> None:
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import compute_promotion_nlists

        db = MagicMock()
        db.ml.get_embedding_stats.return_value = {
            "hot_count": 5,
            "cold_count": 7,
            "index_exists": False,
        }

        with (
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.get_library_record",
                return_value=None,
            ),
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.compute_nlists",
                return_value=12,
            ) as mock_compute_nlists,
        ):
            result = compute_promotion_nlists(db, "effnet", "lib1")

        assert result == 12
        db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_compute_nlists.assert_called_once_with(12, 15)

    @pytest.mark.mocked
    def test_falls_back_to_default_when_group_size_absent(self) -> None:
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import compute_promotion_nlists

        db = MagicMock()
        db.ml.get_embedding_stats.return_value = {
            "hot_count": 2,
            "cold_count": 3,
            "index_exists": False,
        }

        with (
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.get_library_record",
                return_value={"_key": "lib1"},
            ),
            patch(
                f"{ML_IDLE_PROMOTION_MODULE}.compute_nlists",
                return_value=9,
            ) as mock_compute_nlists,
        ):
            result = compute_promotion_nlists(db, "effnet", "lib1")

        assert result == 9
        db.ml.get_embedding_stats.assert_called_once_with("effnet", "lib1")
        mock_compute_nlists.assert_called_once_with(5, 15)
