"""Unit tests for idle_promotion_vectors_wf."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

MODULE_UNDER_TEST = "nomarr.workflows.platform.idle_promotion_vectors_wf"


@pytest.mark.unit
class TestIdlePromotionVectorsWorkflow:
    """Tests for idle_promotion_vectors_workflow."""

    @patch(f"{MODULE_UNDER_TEST}.list_hot_vector_targets")
    def test_returns_zero_when_no_targets(self, mock_targets: MagicMock) -> None:
        """Returns 0 when no hot vector targets exist."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = []
        db = MagicMock()

        result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0

    @patch(f"{MODULE_UNDER_TEST}.promote_and_rebuild_workflow")
    @patch(f"{MODULE_UNDER_TEST}.list_hot_vector_targets")
    @patch(f"{MODULE_UNDER_TEST}.compute_promotion_nlists")
    def test_promotes_when_lock_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Promotes backbones when the distributed lock is successfully acquired."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1"), ("musicnn", "lib2")]
        mock_nlists.return_value = 100

        db = MagicMock()

        with (
            patch(f"{MODULE_UNDER_TEST}.locks_comp.reap_stale_locks") as mock_reap,
            patch(f"{MODULE_UNDER_TEST}.locks_comp.acquire_distributed_lock") as mock_acquire,
            patch(f"{MODULE_UNDER_TEST}.locks_comp.release_distributed_lock") as mock_release,
        ):
            mock_acquire.side_effect = [True, True]

            result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 2
        assert mock_workflow.call_count == 2
        mock_workflow.assert_any_call(db, "effnet", "lib1", 100, "/models")
        mock_workflow.assert_any_call(db, "musicnn", "lib2", 100, "/models")
        mock_reap.assert_called_once_with(db, "worker:tag:0", stale_after_ms=600_000)
        assert mock_acquire.call_args_list == [
            call(db, "vector_promotion", "effnet__lib1", "worker:tag:0", 1800),
            call(db, "vector_promotion", "musicnn__lib2", "worker:tag:0", 1800),
        ]
        assert mock_release.call_args_list == [
            call(db, "vector_promotion", "effnet__lib1", "worker:tag:0"),
            call(db, "vector_promotion", "musicnn__lib2", "worker:tag:0"),
        ]

    @patch(f"{MODULE_UNDER_TEST}.promote_and_rebuild_workflow")
    @patch(f"{MODULE_UNDER_TEST}.list_hot_vector_targets")
    @patch(f"{MODULE_UNDER_TEST}.compute_promotion_nlists")
    def test_skips_when_lock_not_acquired(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Skips promotion when the distributed lock is held elsewhere."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()

        with (
            patch(f"{MODULE_UNDER_TEST}.locks_comp.reap_stale_locks") as mock_reap,
            patch(
                f"{MODULE_UNDER_TEST}.locks_comp.acquire_distributed_lock",
                return_value=False,
            ) as mock_acquire,
            patch(f"{MODULE_UNDER_TEST}.locks_comp.release_distributed_lock") as mock_release,
        ):
            result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0
        mock_workflow.assert_not_called()
        mock_reap.assert_called_once_with(db, "worker:tag:0", stale_after_ms=600_000)
        mock_acquire.assert_called_once_with(db, "vector_promotion", "effnet__lib1", "worker:tag:0", 1800)
        mock_release.assert_not_called()

    @patch(f"{MODULE_UNDER_TEST}.promote_and_rebuild_workflow")
    @patch(f"{MODULE_UNDER_TEST}.list_hot_vector_targets")
    @patch(f"{MODULE_UNDER_TEST}.compute_promotion_nlists")
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

        with (
            patch(f"{MODULE_UNDER_TEST}.locks_comp.reap_stale_locks") as mock_reap,
            patch(
                f"{MODULE_UNDER_TEST}.locks_comp.acquire_distributed_lock",
                return_value=True,
            ) as mock_acquire,
            patch(f"{MODULE_UNDER_TEST}.locks_comp.release_distributed_lock") as mock_release,
        ):
            result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 0
        mock_reap.assert_called_once_with(db, "worker:tag:0", stale_after_ms=600_000)
        mock_acquire.assert_called_once_with(db, "vector_promotion", "effnet__lib1", "worker:tag:0", 1800)
        mock_release.assert_called_once_with(db, "vector_promotion", "effnet__lib1", "worker:tag:0")

    @patch(f"{MODULE_UNDER_TEST}.promote_and_rebuild_workflow")
    @patch(f"{MODULE_UNDER_TEST}.list_hot_vector_targets")
    @patch(f"{MODULE_UNDER_TEST}.compute_promotion_nlists")
    def test_reaps_stale_locks(
        self,
        mock_nlists: MagicMock,
        mock_targets: MagicMock,
        mock_workflow: MagicMock,
    ) -> None:
        """Reaps stale locks before attempting the next promotion target."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow,
        )

        mock_targets.return_value = [("effnet", "lib1")]
        mock_nlists.return_value = 100

        db = MagicMock()

        with (
            patch(f"{MODULE_UNDER_TEST}.locks_comp.reap_stale_locks") as mock_reap,
            patch(
                f"{MODULE_UNDER_TEST}.locks_comp.acquire_distributed_lock",
                return_value=True,
            ) as mock_acquire,
            patch(f"{MODULE_UNDER_TEST}.locks_comp.release_distributed_lock") as mock_release,
        ):
            result = idle_promotion_vectors_workflow(db, "worker:tag:0", "/models")

        assert result == 1
        mock_reap.assert_called_once_with(db, "worker:tag:0", stale_after_ms=600_000)
        mock_acquire.assert_called_once_with(db, "vector_promotion", "effnet__lib1", "worker:tag:0", 1800)
        mock_release.assert_called_once_with(db, "vector_promotion", "effnet__lib1", "worker:tag:0")
        mock_workflow.assert_called_once_with(db, "effnet", "lib1", 100, "/models")
