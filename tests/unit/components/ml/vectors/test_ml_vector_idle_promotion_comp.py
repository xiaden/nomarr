"""Unit tests for ml_vector_idle_promotion_comp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestListHotVectorTargets:
    """Tests for list_hot_vector_targets."""

    @patch("nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.discover_backbones")
    def test_returns_pairs_with_hot_vectors(
        self, mock_discover: MagicMock
    ) -> None:
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
            ops.count.return_value = hot_ops_map.get(
                f"{backbone_id}__{library_key}", 0
            )
            return ops

        db.register_vectors_track_backbone.side_effect = register_backbone

        result = list_hot_vector_targets(db, "/models")

        assert result == [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_discover.assert_called_once_with("/models")

    @patch("nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.discover_backbones")
    def test_returns_empty_when_no_backbones(
        self, mock_discover: MagicMock
    ) -> None:
        """Returns empty list when no backbones discovered."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = []
        db = MagicMock()

        result = list_hot_vector_targets(db, "/models")

        assert result == []
        db.libraries.list_libraries.assert_not_called()

    @patch("nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.discover_backbones")
    def test_returns_empty_when_no_libraries(
        self, mock_discover: MagicMock
    ) -> None:
        """Returns empty list when no libraries exist."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            list_hot_vector_targets,
        )

        mock_discover.return_value = ["effnet"]
        db = MagicMock()
        db.libraries.list_libraries.return_value = []

        result = list_hot_vector_targets(db, "/models")

        assert result == []


@pytest.mark.unit
class TestRunIdlePromotion:
    """Tests for run_idle_promotion."""

    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.list_hot_vector_targets"
    )
    def test_returns_zero_when_no_targets(
        self, mock_targets: MagicMock
    ) -> None:
        """Returns 0 when no hot vector targets exist."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            run_idle_promotion,
        )

        mock_targets.return_value = []
        db = MagicMock()

        result = run_idle_promotion(db, "worker:tag:0", "/models")

        assert result == 0

    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.promote_and_rebuild_workflow"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.list_hot_vector_targets"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp._compute_nlists"
    )
    def test_promotes_when_lock_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Promotes backbones when lock is successfully acquired."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            run_idle_promotion,
        )

        mock_targets.return_value = [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        result = run_idle_promotion(db, "worker:tag:0", "/models")

        assert result == 2
        assert mock_workflow.call_count == 2
        mock_workflow.assert_any_call(db, "effnet", "lib1", 100, "/models")
        mock_workflow.assert_any_call(db, "musicnn", "lib2", 100, "/models")

        # Verify locks released for both
        assert db.vector_promotion_locks.release_lock.call_count == 2
        db.vector_promotion_locks.release_lock.assert_any_call(
            "effnet", "lib1", "worker:tag:0"
        )
        db.vector_promotion_locks.release_lock.assert_any_call(
            "musicnn", "lib2", "worker:tag:0"
        )

    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.promote_and_rebuild_workflow"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.list_hot_vector_targets"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp._compute_nlists"
    )
    def test_skips_when_lock_not_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Skips promotion when lock is held by another worker."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            run_idle_promotion,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = False

        result = run_idle_promotion(db, "worker:tag:0", "/models")

        assert result == 0
        mock_workflow.assert_not_called()
        db.vector_promotion_locks.release_lock.assert_not_called()

    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.promote_and_rebuild_workflow"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.list_hot_vector_targets"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp._compute_nlists"
    )
    def test_releases_lock_on_workflow_failure(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Lock is released even when promote_and_rebuild_workflow raises."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            run_idle_promotion,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100
        mock_workflow.side_effect = RuntimeError("drain failed")

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        result = run_idle_promotion(db, "worker:tag:0", "/models")

        # Promotion failed but lock was still released
        assert result == 0
        db.vector_promotion_locks.release_lock.assert_called_once_with(
            "effnet", "lib1", "worker:tag:0"
        )

    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.promote_and_rebuild_workflow"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp.list_hot_vector_targets"
    )
    @patch(
        "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp._compute_nlists"
    )
    def test_reaps_stale_locks(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Stale locks from crashed workers are force-released."""
        from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
            run_idle_promotion,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = [
            ("yamnet", "lib3"),
        ]
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        run_idle_promotion(db, "worker:tag:0", "/models")

        db.vector_promotion_locks.force_release_lock.assert_called_once_with(
            "yamnet", "lib3"
        )
