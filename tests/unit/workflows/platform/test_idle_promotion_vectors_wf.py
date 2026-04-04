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
    def test_returns_zero_when_no_targets(self, mock_targets: MagicMock) -> None:
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
        db.locks.get_stale_locks.return_value = []
        db.locks.try_acquire.return_value = True

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 2
        assert mock_workflow.call_count == 2
        mock_workflow.assert_any_call(db, "effnet", "lib1", 100, "/models")
        mock_workflow.assert_any_call(db, "musicnn", "lib2", 100, "/models")

        # Verify locks released for both
        assert db.locks.release.call_count == 2
        db.locks.release.assert_any_call("vector_promotion", "effnet__lib1", "worker:tag:0")
        db.locks.release.assert_any_call("vector_promotion", "musicnn__lib2", "worker:tag:0")

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
        db.locks.get_stale_locks.return_value = []
        db.locks.try_acquire.return_value = False

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0
        mock_workflow.assert_not_called()
        db.locks.release.assert_not_called()

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
        db.locks.get_stale_locks.return_value = []
        db.locks.try_acquire.return_value = True

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        # Promotion failed but lock was still released
        assert result == 0
        db.locks.release.assert_called_once_with("vector_promotion", "effnet__lib1", "worker:tag:0")

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
        # New format: get_stale_locks returns (lock_type, resource_id) tuples
        db.locks.get_stale_locks.return_value = [
            ("vector_promotion", "yamnet__lib3"),
        ]
        db.locks.try_acquire.return_value = True

        idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        db.locks.force_release.assert_called_once_with("vector_promotion", "yamnet__lib3")
