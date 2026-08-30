"""Pipeline transition tests for ``nomarr.workflows.library.scan_setup_wf``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import DuplicateEntityError, LibraryAlreadyScanningError
from nomarr.workflows.library.scan_setup_wf import scan_setup_workflow


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name="Main Library", root_path="/music")


class TestScanSetupWorkflowPipeline:
    """Tests for scan-start pipeline transitions."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_setup_transitions_library_to_scanning_pipeline_state(self) -> None:
        """Scan setup should move the library pipeline state to scanning."""
        mock_db = MagicMock()
        library = _make_library()

        with (
            patch(
                "nomarr.workflows.library.scan_setup_wf.check_interrupted_scan",
                return_value=(False, None),
            ),
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=False),
            patch("nomarr.workflows.library.scan_setup_wf.mark_scan_started") as mock_start,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition_to_scanning,
        ):
            result = scan_setup_workflow(mock_db, library, scan_type="quick")

        assert result == library
        assert mock_transition_to_scanning.called
        mock_start.assert_called_once_with(mock_db, library, "quick")
        mock_transition_to_scanning.assert_called_once_with(mock_db, library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_setup_rejects_library_already_in_scanning_pipeline_state(self) -> None:
        """Duplicate scans should be rejected when the pipeline state is already scanning."""
        mock_db = MagicMock()
        library = _make_library()

        with (
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=True),
            patch("nomarr.workflows.library.scan_setup_wf.mark_scan_started") as mock_start,
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition,
            pytest.raises(LibraryAlreadyScanningError, match="already being scanned"),
        ):
            scan_setup_workflow(mock_db, library, scan_type="quick")

        mock_start.assert_not_called()
        mock_transition.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_setup_maps_concurrent_active_scan_insert_to_already_scanning(self) -> None:
        """A unique active-row violation rejects the losing concurrent request."""
        mock_db = MagicMock()
        library = _make_library()

        with (
            patch("nomarr.workflows.library.scan_setup_wf.check_interrupted_scan", return_value=(False, None)),
            patch("nomarr.workflows.library.scan_setup_wf.is_library_scanning", return_value=False),
            patch(
                "nomarr.workflows.library.scan_setup_wf.mark_scan_started",
                side_effect=DuplicateEntityError("active scan already exists"),
            ),
            patch("nomarr.workflows.library.scan_setup_wf.transition_to_scanning") as mock_transition,
            pytest.raises(LibraryAlreadyScanningError, match="already being scanned"),
        ):
            scan_setup_workflow(mock_db, library, scan_type="quick")

        mock_transition.assert_not_called()
