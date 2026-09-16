"""Regression tests for scan preflight failures not stranding a library in ``scanning``.

Issue ``issue_04_scan_preflight_failure_can_leave_scan_permanently_in_progress``.

Scan admission (``scan_setup_workflow``) establishes the ``scanning`` axis before
the background scan workflow runs. Both scan workflows historically resolved the
library and validated its filesystem root *before* entering their failure-handling
``try/except``. A preflight failure (unmounted/inaccessible root, or a library
deleted between admission and worker execution) therefore bypassed the cleanup
that resets ``scan_state`` to ``not_scanned``, violating ASR-0004.

These tests assert that a preflight failure still reaches the cleanup boundary
and resets the scan axis to ``not_scanned``.
"""

from __future__ import annotations

import errno
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.pipeline_states import SCAN_NOT_SCANNED, SCAN_STATE_FIELD
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import LibraryNotFoundError
from nomarr.workflows.library.scan_library_full_wf import scan_library_full_workflow
from nomarr.workflows.library.scan_library_quick_wf import scan_library_quick_workflow


def _library() -> Library:
    """A library whose root does not exist on disk (unmounted volume simulation)."""
    return Library(name="Unmounted Library", root_path="/nonexistent/nomarr/root")


WORKFLOWS = (
    ("nomarr.workflows.library.scan_library_quick_wf", scan_library_quick_workflow),
    ("nomarr.workflows.library.scan_library_full_wf", scan_library_full_workflow),
)


class TestScanPreflightFailureRecovery:
    """Preflight failures must not strand a library in the scanning state."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("module_path", "workflow"), WORKFLOWS)
    def test_root_validation_failure_resets_scan_axis(self, module_path: str, workflow) -> None:
        """An unmounted/inaccessible root must reset scan_state to not_scanned."""
        mock_db = MagicMock()
        library = _library()

        with (
            patch(f"{module_path}.resolve_library_for_scan", return_value=library),
            patch(f"{module_path}.update_scan_progress") as mock_progress,
            patch(f"{module_path}.transition_pipeline_axis") as mock_transition,
            pytest.raises(OSError, match="does not exist"),
        ):
            workflow(mock_db, library, tagger_version="v1")

        mock_progress.assert_called_once()
        assert "does not exist" in mock_progress.call_args.kwargs["scan_error"]
        mock_transition.assert_called_once_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("module_path", "workflow"), WORKFLOWS)
    def test_library_resolution_failure_resets_scan_axis(self, module_path: str, workflow) -> None:
        """A library deleted between admission and execution must record failure and reset scan_state.

        The reset is asserted because the workflow now reaches its cleanup boundary
        on a resolution failure. In a real database the transition is moot — the
        library row (and its ``scanning`` pipeline state) is cascade-deleted with
        the library — but the failure must still be recorded and re-raised.
        """
        mock_db = MagicMock()
        library = _library()

        with (
            patch(
                f"{module_path}.resolve_library_for_scan",
                side_effect=LibraryNotFoundError("library gone"),
            ),
            patch(f"{module_path}.update_scan_progress") as mock_progress,
            patch(f"{module_path}.transition_pipeline_axis") as mock_transition,
            pytest.raises(LibraryNotFoundError),
        ):
            workflow(mock_db, library, tagger_version="v1")

        mock_progress.assert_called_once()
        assert mock_progress.call_args.kwargs["scan_error"] == "library gone"
        mock_transition.assert_called_once_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("module_path", "workflow"), WORKFLOWS)
    def test_errno_preflight_failure_names_kind_and_resets_scan_axis(self, module_path: str, workflow) -> None:
        """A classified preflight failure (EACCES -> permission_denied) must carry a
        kind-named message — never a claim that the root does not exist — preserve the
        errno, record the failure, and reset the scan axis."""
        mock_db = MagicMock()
        library = _library()

        with (
            patch(f"{module_path}.resolve_library_for_scan", return_value=library),
            patch(f"{module_path}.validate_library_root", side_effect=OSError(errno.EACCES, "denied")),
            patch(f"{module_path}.update_scan_progress") as mock_progress,
            patch(f"{module_path}.transition_pipeline_axis") as mock_transition,
            pytest.raises(OSError, match="permission_denied") as exc_info,
        ):
            workflow(mock_db, library, tagger_version="v1")

        assert exc_info.value.errno == errno.EACCES
        assert "does not exist" not in str(exc_info.value)
        mock_progress.assert_called_once()
        assert "permission_denied" in mock_progress.call_args.kwargs["scan_error"]
        mock_transition.assert_called_once_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("module_path", "workflow"), WORKFLOWS)
    def test_errno_less_preflight_failure_classifies_unknown_and_resets_scan_axis(
        self, module_path: str, workflow
    ) -> None:
        """An errno-less validation failure classifies as ``unknown``: the message
        must not claim the root does not exist, ``errno`` stays ``None``, the failure
        is recorded, and the scan axis is reset (still recoverable)."""
        mock_db = MagicMock()
        library = _library()

        with (
            patch(f"{module_path}.resolve_library_for_scan", return_value=library),
            patch(f"{module_path}.validate_library_root", side_effect=OSError("no errno available")),
            patch(f"{module_path}.update_scan_progress") as mock_progress,
            patch(f"{module_path}.transition_pipeline_axis") as mock_transition,
            pytest.raises(OSError, match="unknown") as exc_info,
        ):
            workflow(mock_db, library, tagger_version="v1")

        assert exc_info.value.errno is None
        assert "does not exist" not in str(exc_info.value)
        mock_progress.assert_called_once()
        assert "unknown" in mock_progress.call_args.kwargs["scan_error"]
        mock_transition.assert_called_once_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
