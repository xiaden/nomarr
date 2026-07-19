"""Tests for ``nomarr.workflows.library.reconcile_paths_wf``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.workflows.library.reconcile_paths_wf import reconcile_library_paths_workflow


class TestReconcileLibraryPathsWorkflow:
    """Tests for ``reconcile_library_paths_workflow``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("library_root", [None, ""])
    def test_raises_when_library_root_missing(self, library_root: str | None) -> None:
        """Missing library root should raise ValueError before delegation."""
        with pytest.raises(ValueError, match="Library root not configured"):
            reconcile_library_paths_workflow(
                db=MagicMock(),
                library_id="libraries/1",
                library_root=library_root,
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_policy_invalid(self) -> None:
        """Unknown reconciliation policy should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid policy 'bad_policy'"):
            reconcile_library_paths_workflow(
                db=MagicMock(),
                library_id="libraries/1",
                library_root="/music",
                policy="bad_policy",  # type: ignore[arg-type]
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_component_with_expected_arguments(self) -> None:
        """Valid calls should forward library_id, policy, and batch_size unchanged."""
        mock_db = MagicMock()
        expected_result = {
            "total_files": 10,
            "valid_files": 8,
            "invalid_config": 1,
            "not_found": 1,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        with patch(
            "nomarr.workflows.library.reconcile_paths_wf.reconcile_library_paths",
            return_value=expected_result,
        ) as mock_reconcile_library_paths:
            result = reconcile_library_paths_workflow(
                db=mock_db,
                library_id="libraries/1",
                library_root="/music",
                policy="delete_invalid",
                batch_size=250,
            )

        assert result is expected_result
        mock_reconcile_library_paths.assert_called_once_with(
            db=mock_db,
            library_id="libraries/1",
            policy="delete_invalid",
            batch_size=250,
        )
