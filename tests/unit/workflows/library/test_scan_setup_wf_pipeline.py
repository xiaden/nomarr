"""Pipeline transition tests for ``nomarr.workflows.library.scan_setup_wf``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.library_pipeline_states_aql import PIPELINE_SCANNING
from nomarr.workflows.library.scan_setup_wf import scan_setup_workflow


class TestScanSetupWorkflowPipeline:
    """Tests for scan-start pipeline transitions."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def helper_scan_setup_transitions_library_to_scanning_pipeline_state(self) -> None:
        """Scan setup should move the library pipeline state to scanning."""
        mock_db = MagicMock()
        library = {"_id": "libraries/abc123", "name": "Main Library", "scan_status": "idle"}

        with (
            patch(
                "nomarr.workflows.library.scan_setup_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch(
                "nomarr.workflows.library.scan_setup_wf.check_interrupted_scan",
                return_value=(False, None),
            ),
            patch("nomarr.workflows.library.scan_setup_wf.update_scan_progress") as mock_update,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition_to_scanning,
        ):
            result = scan_setup_workflow(mock_db, "libraries/abc123", scan_type="quick")

        assert result == library
        assert mock_transition_to_scanning.called
        mock_update.assert_called_once_with(
            mock_db,
            "libraries/abc123",
            status="scanning",
            progress=0,
            total=0,
        )
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            "libraries/abc123",
            PIPELINE_SCANNING,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_setup_transitions_library_to_scanning_pipeline_state(self) -> None:
        """Scan setup should move the library pipeline state to scanning."""
        mock_db = MagicMock()
        library = {"_id": "libraries/abc123", "name": "Main Library", "scan_status": "idle"}

        with (
            patch(
                "nomarr.workflows.library.scan_setup_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch(
                "nomarr.workflows.library.scan_setup_wf.check_interrupted_scan",
                return_value=(False, None),
            ),
            patch("nomarr.workflows.library.scan_setup_wf.update_scan_progress") as mock_update,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition_to_scanning,
        ):
            result = scan_setup_workflow(mock_db, "libraries/abc123", scan_type="quick")

        assert result == library
        assert mock_transition_to_scanning.called
        mock_update.assert_called_once_with(
            mock_db,
            "libraries/abc123",
            status="scanning",
            progress=0,
            total=0,
        )
        mock_transition_to_scanning.assert_called_once_with(
            mock_db,
            "libraries/abc123",
        )
