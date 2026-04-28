"""Pipeline transition tests for ``nomarr.workflows.library.scan_setup_wf``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.exceptions import LibraryAlreadyScanningError
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
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=False),
            patch("nomarr.workflows.library.scan_setup_wf.update_scan_progress") as mock_update,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition_to_scanning,
        ):
            result = scan_setup_workflow(mock_db, "libraries/abc123", scan_type="quick")

        assert result == library
        assert mock_transition_to_scanning.called
        mock_update.assert_called_once_with(
            mock_db,
            "libraries/abc123",
            progress=0,
            total=0,
        )
        mock_transition_to_scanning.assert_called_once_with(mock_db, "libraries/abc123")

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
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=False),
            patch("nomarr.workflows.library.scan_setup_wf.update_scan_progress") as mock_update,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition_to_scanning,
        ):
            result = scan_setup_workflow(mock_db, "libraries/abc123", scan_type="quick")

        assert result == library
        assert mock_transition_to_scanning.called
        mock_update.assert_called_once_with(
            mock_db,
            "libraries/abc123",
            progress=0,
            total=0,
        )
        mock_transition_to_scanning.assert_called_once_with(
            mock_db,
            "libraries/abc123",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_setup_rejects_library_already_in_scanning_pipeline_state(self) -> None:
        """Duplicate scans should be rejected when the pipeline state is already scanning."""
        mock_db = MagicMock()
        library = {"_id": "libraries/abc123", "name": "Main Library", "scan_status": "idle"}

        with (
            patch(
                "nomarr.workflows.library.scan_setup_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=True),
            patch("nomarr.workflows.library.scan_setup_wf.update_scan_progress") as mock_update,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition,
            pytest.raises(LibraryAlreadyScanningError, match="already being scanned"),
        ):
            scan_setup_workflow(mock_db, "libraries/abc123", scan_type="quick")

        mock_update.assert_not_called()
        mock_transition.assert_not_called()
