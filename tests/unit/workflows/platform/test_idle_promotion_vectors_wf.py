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
        db.locks.count.return_value = 2
        db.locks.acquired_at.get.in_.return_value = []
        db.locks.document_reference.get.side_effect = [
            None,
            {"holder": "worker:tag:0"},
            None,
            {"holder": "worker:tag:0"},
        ]
        db.locks.document_reference.delete.return_value = 1

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 2
        assert mock_workflow.call_count == 2
        mock_workflow.assert_any_call(db, "effnet", "lib1", 100, "/models")
        mock_workflow.assert_any_call(db, "musicnn", "lib2", 100, "/models")

        assert db.locks.insert.call_count == 2
        assert db.locks.document_reference.delete.call_count == 2
        db.locks.document_reference.delete.assert_any_call("vector_promotion:effnet__lib1")
        db.locks.document_reference.delete.assert_any_call("vector_promotion:musicnn__lib2")

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
        db.locks.count.return_value = 1
        db.locks.acquired_at.get.in_.return_value = []
        db.locks.document_reference.get.return_value = {
            "document_reference": "vector_promotion:effnet__lib1",
            "holder": "other-worker",
            "expires_at": 9_999_999_999_999.0,
        }

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0
        mock_workflow.assert_not_called()
        db.locks.insert.assert_not_called()
        db.locks.document_reference.delete.assert_not_called()

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
        db.locks.count.return_value = 1
        db.locks.acquired_at.get.in_.return_value = []
        db.locks.document_reference.get.side_effect = [None, {"holder": "worker:tag:0"}]
        db.locks.document_reference.delete.return_value = 1

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        # Promotion failed but lock was still released
        assert result == 0
        db.locks.document_reference.delete.assert_called_once_with("vector_promotion:effnet__lib1")

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
        db.locks.count.return_value = 2
        db.locks.acquired_at.get.in_.return_value = [
            {
                "document_reference": "vector_promotion:yamnet__lib3",
                "lock_type": "vector_promotion",
            },
        ]
        db.locks.document_reference.get.side_effect = [None, {"holder": "worker:tag:0"}]
        db.locks.document_reference.delete.return_value = 1

        idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        db.locks.document_reference.delete.assert_any_call("vector_promotion:yamnet__lib3")
