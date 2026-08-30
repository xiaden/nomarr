"""Terminal-semantics tests for cooperative scan cancellation.

Proves that a dispatched quick-scan ``ManagedTask`` whose ``stop_event`` is set
ends in the BTS ``cancelled`` terminal state — not ``complete`` — with the
completion hook skipped and the scan axis reset to ``not_scanned``.
"""

from __future__ import annotations

import functools
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.helpers.constants.pipeline_states import SCAN_NOT_SCANNED, SCAN_STATE_FIELD
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.services.domain.library_svc.task_ids import library_task_id
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
from nomarr.workflows.library.scan_library_full_wf import scan_library_full_workflow
from nomarr.workflows.library.scan_library_quick_wf import scan_library_quick_workflow


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name="Main Library", root_path="/music")


class TestScanCancellationTerminal:
    """Tests for the scan-cancellation terminal path through a real BTS."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancellation_records_cancelled_and_skips_on_complete(self) -> None:
        """A set stop_event must surface ScanCancelledError as 'cancelled', skip on_complete, reset axis."""
        mock_db = MagicMock()
        library = _make_library()
        on_complete_calls: list[str] = []
        stop_event = threading.Event()
        stop_event.set()  # cancellation requested before dispatch

        # Mirror the dispatch wiring in LibraryScanMixin.start_quick_scan.
        task = ManagedTask(
            task_id=library_task_id(library, "scan"),
            fn=functools.partial(
                scan_library_quick_workflow,
                db=mock_db,
                library=library,
                tagger_version="tagger-v1",
                stop_event=stop_event,
            ),
            stop_event=stop_event,
            on_complete=lambda: on_complete_calls.append("called"),
            daemon=True,
        )

        with (
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch("nomarr.workflows.library.scan_library_quick_wf.validate_library_root"),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.get_folder_rel_paths",
                return_value=set(),
            ),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.get_cached_folders",
                return_value={},
            ),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.discover_library_folders",
                return_value=[SimpleNamespace(rel_path="f1", file_count=1)],
            ),
            patch("nomarr.workflows.library.scan_library_quick_wf.update_scan_progress") as mock_progress,
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.transition_pipeline_axis",
            ) as mock_transition,
        ):
            bts = BackgroundTaskService()
            task_id = bts.start_task(task)
            thread = bts._tasks[task_id][0]
            thread.join(timeout=2.0)

        assert not thread.is_alive()
        status = bts.get_task_status(task_id)
        assert status is not None
        assert status["status"] == "cancelled"
        assert status["result"] is None
        assert status["error"] is None
        # The completion hook must not run for a cancelled scan.
        assert on_complete_calls == []
        # The scan workflow records cancellation as an error and resets the axis.
        mock_progress.assert_any_call(mock_db, library, status="error", scan_error="Scan cancelled by user")
        mock_transition.assert_called_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_full_scan_cancellation_records_cancelled_and_skips_on_complete(self) -> None:
        """Full scans use the same cancelled terminal contract as quick scans."""
        mock_db = MagicMock()
        library = _make_library()
        on_complete_calls: list[str] = []
        stop_event = threading.Event()
        stop_event.set()
        task = ManagedTask(
            task_id=library_task_id(library, "scan"),
            fn=functools.partial(
                scan_library_full_workflow,
                db=mock_db,
                library=library,
                tagger_version="tagger-v1",
                stop_event=stop_event,
            ),
            stop_event=stop_event,
            on_complete=lambda: on_complete_calls.append("called"),
        )

        with (
            patch("nomarr.workflows.library.scan_library_full_wf.resolve_library_for_scan", return_value=library),
            patch("nomarr.workflows.library.scan_library_full_wf.validate_library_root"),
            patch("nomarr.workflows.library.scan_library_full_wf.get_folder_rel_paths", return_value=set()),
            patch("nomarr.workflows.library.scan_library_full_wf.get_cached_folders", return_value={}),
            patch(
                "nomarr.workflows.library.scan_library_full_wf.discover_library_folders",
                return_value=[SimpleNamespace(rel_path="f1", file_count=1)],
            ),
            patch("nomarr.workflows.library.scan_library_full_wf.update_scan_progress") as mock_progress,
            patch("nomarr.workflows.library.scan_library_full_wf.transition_pipeline_axis") as mock_transition,
        ):
            bts = BackgroundTaskService()
            task_id = bts.start_task(task)
            thread = bts._tasks[task_id][0]
            thread.join(timeout=2.0)

        assert not thread.is_alive()
        status = bts.get_task_status(task_id)
        assert status is not None and status["status"] == "cancelled"
        assert on_complete_calls == []
        mock_progress.assert_any_call(mock_db, library, status="error", scan_error="Scan cancelled by user")
        mock_transition.assert_called_with(mock_db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
