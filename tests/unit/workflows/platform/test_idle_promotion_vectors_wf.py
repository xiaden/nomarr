"""Unit tests for idle_promotion_vectors_wf."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

COMP_MODULE = "nomarr.components.ml.vectors.ml_vector_idle_promotion_comp"
WF_MODULE = "nomarr.workflows.platform.promote_and_rebuild_vectors_wf"


@pytest.mark.unit
class TestIdlePromotionVectorsWorkflow:
    """Tests for idle_promotion_vectors_workflow."""

    @patch(f"{COMP_MODULE}.list_hot_vector_targets")
    def test_returns_zero_when_no_targets(
        self, mock_targets: MagicMock
    ) -> None:
        """Returns 0 when no hot vector targets exist."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = []
        db = MagicMock()

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0

    @patch(f"{WF_MODULE}.promote_and_rebuild_workflow")
    @patch(f"{COMP_MODULE}.list_hot_vector_targets")
    @patch(f"{COMP_MODULE}.compute_promotion_nlists")
    def test_promotes_when_lock_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Promotes backbones when lock is successfully acquired."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

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

    @patch(f"{WF_MODULE}.promote_and_rebuild_workflow")
    @patch(f"{COMP_MODULE}.list_hot_vector_targets")
    @patch(f"{COMP_MODULE}.compute_promotion_nlists")
    def test_skips_when_lock_not_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Skips promotion when lock is held by another worker."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = False

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0
        mock_workflow.assert_not_called()
        db.vector_promotion_locks.release_lock.assert_not_called()

    @patch(f"{WF_MODULE}.promote_and_rebuild_workflow")
    @patch(f"{COMP_MODULE}.list_hot_vector_targets")
    @patch(f"{COMP_MODULE}.compute_promotion_nlists")
    def test_releases_lock_on_workflow_failure(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Lock is released even when promote_and_rebuild_workflow raises."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100
        mock_workflow.side_effect = RuntimeError("drain failed")

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = []
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        # Promotion failed but lock was still released
        assert result == 0
        db.vector_promotion_locks.release_lock.assert_called_once_with(
            "effnet", "lib1", "worker:tag:0"
        )

    @patch(f"{WF_MODULE}.promote_and_rebuild_workflow")
    @patch(f"{COMP_MODULE}.list_hot_vector_targets")
    @patch(f"{COMP_MODULE}.compute_promotion_nlists")
    def test_reaps_stale_locks(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Stale locks from crashed workers are force-released."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()
        db.vector_promotion_locks.get_stale_locks.return_value = [
            ("yamnet", "lib3"),
        ]
        db.vector_promotion_locks.try_acquire_lock.return_value = True

        idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        db.vector_promotion_locks.force_release_lock.assert_called_once_with(
            "yamnet", "lib3"
        )
