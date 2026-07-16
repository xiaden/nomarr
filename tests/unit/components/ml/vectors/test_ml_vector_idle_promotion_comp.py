"""Unit tests for ml_vector_idle_promotion_comp."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

ML_IDLE_PROMOTION_MODULE = "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp"


@pytest.mark.unit
class TestListHotVectorTargets:
    """Tests for list_hot_vector_targets."""

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    async def test_returns_backbones_with_hot_vectors(self, mock_discover: AsyncMock) -> None:
        """Returns backbone IDs where hot count > 0 (no library enumeration)."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet", "musicnn"]

        db = AsyncMock()

        def get_embedding_stats(backbone_id: str) -> dict:
            counts = {
                "effnet": 42,
                "musicnn": 0,
            }
            hot = counts.get(backbone_id, 0)
            return {
                "hot_count": hot,
                "cold_count": 0,
                "index_exists": False,
            }

        db.ml.get_embedding_stats.side_effect = get_embedding_stats

        result = await list_hot_vector_targets(db, "/models")

        assert result == ["effnet"]
        mock_discover.assert_called_once_with("/models")

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    async def test_returns_empty_when_no_backbones(self, mock_discover: AsyncMock) -> None:
        """Returns empty list when no backbones discovered."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = []
        db = AsyncMock()

        result = await list_hot_vector_targets(db, "/models")

        assert result == []
        db.ml.get_embedding_stats.assert_not_called()

    @patch(f"{ML_IDLE_PROMOTION_MODULE}.discover_backbones")
    async def test_filters_out_backbones_with_no_hot_vectors(self, mock_discover: AsyncMock) -> None:
        """Backbones with zero or missing hot collections are excluded."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet", "yamnet", "musicnn"]

        db = AsyncMock()

        def get_embedding_stats(backbone_id: str) -> dict:
            counts = {"effnet": 0, "yamnet": 5}
            hot = counts.get(backbone_id, 0)
            return {
                "hot_count": hot,
                "cold_count": 0,
                "index_exists": False,
            }

        db.ml.get_embedding_stats.side_effect = get_embedding_stats

        result = await list_hot_vector_targets(db, "/models")

        assert result == ["yamnet"]


@pytest.mark.unit
class TestComputePromotionEfConstruction:
    """Tests for ``compute_promotion_ef_construction``."""

    @pytest.mark.mocked
    async def test_uses_global_default_group_size(self) -> None:
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import compute_promotion_ef_construction

        db = AsyncMock()
        db.ml.get_embedding_stats.return_value = {
            "hot_count": 100,
            "cold_count": 200,
            "index_exists": False,
        }

        with patch(
            f"{ML_IDLE_PROMOTION_MODULE}.get_ef_construction",
            return_value=37,
        ) as mock_get_ef:
            result = await compute_promotion_ef_construction(db, "effnet")

        assert result == 37
        db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_get_ef.assert_called_once_with(300)

    @pytest.mark.mocked
    async def test_uses_total_vector_count_from_both_hot_and_cold(self) -> None:
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import compute_promotion_ef_construction

        db = AsyncMock()
        db.ml.get_embedding_stats.return_value = {
            "hot_count": 5,
            "cold_count": 7,
            "index_exists": False,
        }

        with patch(
            f"{ML_IDLE_PROMOTION_MODULE}.get_ef_construction",
            return_value=12,
        ) as mock_get_ef:
            result = await compute_promotion_ef_construction(db, "effnet")

        assert result == 12
        db.ml.get_embedding_stats.assert_called_once_with("effnet")
        mock_get_ef.assert_called_once_with(12)
