"""Unit tests for ml_vector_idle_promotion_comp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

DISCOVERY_MODULE = "nomarr.components.ml.onnx.ml_discovery_comp"


@pytest.mark.unit
class TestListHotVectorTargets:
    """Tests for list_hot_vector_targets."""

    @patch(f"{DISCOVERY_MODULE}.discover_backbones")
    def test_returns_pairs_with_hot_vectors(self, mock_discover: MagicMock) -> None:
        """Returns (backbone, library) pairs where hot count > 0."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet", "musicnn"]

        db = MagicMock()
        db.libraries.list_libraries.return_value = [
            {"_key": "lib1"},
            {"_key": "lib2"},
        ]

        # effnet__lib1 has vectors, effnet__lib2 does not exist,
        # musicnn__lib1 exists but empty, musicnn__lib2 has vectors
        def has_collection(name: str) -> bool:
            return name in {
                "vectors_track_hot__effnet__lib1",
                "vectors_track_hot__musicnn__lib1",
                "vectors_track_hot__musicnn__lib2",
            }

        db.db.has_collection.side_effect = has_collection

        # Mock hot ops count per (backbone, library)
        hot_ops_map: dict[str, int] = {
            "effnet__lib1": 42,
            "musicnn__lib1": 0,
            "musicnn__lib2": 10,
        }

        def register_backbone(backbone_id: str, library_key: str) -> MagicMock:
            ops = MagicMock()
            ops.count.return_value = hot_ops_map.get(f"{backbone_id}__{library_key}", 0)
            return ops

        db.register_vectors_track_backbone.side_effect = register_backbone

        result = list_hot_vector_targets(db, "/models")

        assert result == [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_discover.assert_called_once_with("/models")

    @patch(f"{DISCOVERY_MODULE}.discover_backbones")
    def test_returns_empty_when_no_backbones(self, mock_discover: MagicMock) -> None:
        """Returns empty list when no backbones discovered."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = []
        db = MagicMock()

        result = list_hot_vector_targets(db, "/models")

        assert result == []
        db.libraries.list_libraries.assert_not_called()

    @patch(f"{DISCOVERY_MODULE}.discover_backbones")
    def test_returns_empty_when_no_libraries(self, mock_discover: MagicMock) -> None:
        """Returns empty list when no libraries exist."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet"]
        db = MagicMock()
        db.libraries.list_libraries.return_value = []

        result = list_hot_vector_targets(db, "/models")

        assert result == []
