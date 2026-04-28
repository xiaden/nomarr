"""Unit tests for LibraryPipelineService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_APPLYING,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_DONE,
    PIPELINE_IDLE,
    PIPELINE_SCANNING,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
)
from nomarr.services.domain.calibration_svc import CALIBRATION_GENERATE_TASK_ID
from nomarr.services.domain.tagging_svc import CALIBRATION_APPLY_TASK_ID
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mocked database dependency."""
    return MagicMock()


@pytest.fixture
def mock_bts() -> MagicMock:
    """Provide a mocked background task service dependency."""
    return MagicMock()


@pytest.fixture
def mock_calibration_svc() -> MagicMock:
    """Provide a mocked calibration service dependency."""
    return MagicMock()


@pytest.fixture
def mock_tagging_svc() -> MagicMock:
    """Provide a mocked tagging service dependency."""
    return MagicMock()


@pytest.fixture
def mock_navidrome_svc() -> MagicMock:
    """Provide a mocked Navidrome service dependency."""
    return MagicMock()


@pytest.fixture(autouse=True)
def pipeline_state_helper_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge helper-based production code to the existing service-level mock API."""

    def _update_scan_progress(
        db: MagicMock,
        library_id: str,
        *,
        progress: int | None = None,
        total: int | None = None,
        scan_error: str | None = None,
        completed_at: int | None = None,
        started_at: int | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if progress is not None:
            kwargs["progress"] = progress
        if total is not None:
            kwargs["total"] = total
        if scan_error is not None:
            kwargs["error"] = scan_error
        if completed_at is not None:
            kwargs["completed_at"] = completed_at
        if started_at is not None:
            kwargs["started_at"] = started_at
        db.libraries.update_scan_status(library_id, **kwargs)

    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_library_record",
        lambda db, library_id, **_kwargs: db.libraries.get_library(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_libraries_in_pipeline_state",
        lambda db, state: db.library_pipeline_states.get_libraries_in_state(state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.bulk_transition_pipeline_state",
        lambda db, from_state, to_state: db.library_pipeline_states.bulk_transition(from_state, to_state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.transition_pipeline_state",
        lambda db, library_id, state: db.library_pipeline_states.transition_state(library_id, state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_pipeline_state",
        lambda db, library_id: db.library_pipeline_states.get_state(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.count_untagged_files",
        lambda db, library_id: db.library_files.count_untagged_files(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_uncalibrated_tagged_file_ids",
        lambda db, library_id: db.library_files.get_uncalibrated_tagged_file_ids(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.update_scan_progress",
        _update_scan_progress,
    )


@pytest.fixture
def pipeline_service(
    mock_db: MagicMock,
    mock_bts: MagicMock,
    mock_calibration_svc: MagicMock,
    mock_tagging_svc: MagicMock,
    mock_navidrome_svc: MagicMock,
) -> LibraryPipelineService:
    """Build the service under test with mocked collaborators."""
    return LibraryPipelineService(
        db=mock_db,
        bts=mock_bts,
        calibration_svc=mock_calibration_svc,
        tagging_svc=mock_tagging_svc,
        navidrome_svc=mock_navidrome_svc,
    )


class TestRecoverStaleStates:
    """Tests for startup stale-state recovery."""

    def test_recover_stale_states_scanning(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Missing scan task should bulk-transition scanning libraries to idle."""
        library_id = "libraries/lib1"
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [[library_id], []]
        mock_db.library_pipeline_states.bulk_transition.side_effect = lambda from_state, to_state: (
            1 if (from_state, to_state) == (PIPELINE_SCANNING, PIPELINE_IDLE) else 0
        )

        def get_task_status(task_id: str) -> dict[str, str] | None:
            if task_id == f"scan_library_{library_id}":
                return None
            return {"status": "running"}

        mock_bts.get_task_status.side_effect = get_task_status

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 1, "calibrating": 0, "applying": 0, "writing": 0}
        mock_db.library_pipeline_states.bulk_transition.assert_any_call(PIPELINE_SCANNING, PIPELINE_IDLE)
        mock_db.libraries.update_scan_status.assert_called_once_with(
            library_id,
            error="Scan interrupted by server restart",
        )

    def test_recover_stale_states_calibrating(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Missing calibration-generate task should restore libraries to awaiting_calibration."""
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [[], []]
        mock_db.library_pipeline_states.bulk_transition.side_effect = lambda from_state, to_state: (
            2 if (from_state, to_state) == (PIPELINE_CALIBRATING, PIPELINE_AWAITING_CALIBRATION) else 0
        )

        def get_task_status(task_id: str) -> dict[str, str] | None:
            if task_id == CALIBRATION_GENERATE_TASK_ID:
                return None
            return {"status": "running"}

        mock_bts.get_task_status.side_effect = get_task_status

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 0, "calibrating": 2, "applying": 0, "writing": 0}
        mock_db.library_pipeline_states.bulk_transition.assert_any_call(
            PIPELINE_CALIBRATING,
            PIPELINE_AWAITING_CALIBRATION,
        )
        mock_db.libraries.update_scan_status.assert_not_called()

    def test_recover_stale_states_applying(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Missing calibration-apply task should restore libraries to awaiting_calibration."""
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [[], []]
        mock_db.library_pipeline_states.bulk_transition.side_effect = lambda from_state, to_state: (
            3 if (from_state, to_state) == (PIPELINE_APPLYING, PIPELINE_AWAITING_CALIBRATION) else 0
        )

        def get_task_status(task_id: str) -> dict[str, str] | None:
            if task_id == CALIBRATION_APPLY_TASK_ID:
                return None
            return {"status": "running"}

        mock_bts.get_task_status.side_effect = get_task_status

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 0, "calibrating": 0, "applying": 3, "writing": 0}
        mock_db.library_pipeline_states.bulk_transition.assert_any_call(
            PIPELINE_APPLYING,
            PIPELINE_AWAITING_CALIBRATION,
        )
        mock_db.libraries.update_scan_status.assert_not_called()

    def test_recover_stale_states_writing(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Missing write-tags task should move writing libraries back to write_ready."""
        library_id = "libraries/lib-write"
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [[], [library_id]]
        mock_bts.get_task_status.side_effect = lambda task_id: (
            None if task_id == f"write_tags:{library_id}" else {"status": "running"}
        )

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 0, "calibrating": 0, "applying": 0, "writing": 1}
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(library_id, PIPELINE_WRITE_READY)
        mock_db.libraries.update_scan_status.assert_not_called()


class TestTriggerCalibration:
    """Tests for calibration trigger orchestration."""

    def test_trigger_calibration_no_libraries(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_calibration_svc: MagicMock,
    ) -> None:
        """Should return early when no libraries are awaiting calibration."""
        mock_db.calibration_state.count.return_value = 0
        mock_db.library_pipeline_states.bulk_transition.return_value = 0

        pipeline_service.trigger_calibration()

        mock_db.library_pipeline_states.bulk_transition.assert_called_once_with(
            PIPELINE_AWAITING_CALIBRATION,
            PIPELINE_CALIBRATING,
        )
        mock_calibration_svc.start_histogram_calibration_background.assert_not_called()

    def test_trigger_calibration_no_existing_calibration(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_calibration_svc: MagicMock,
    ) -> None:
        """Should start histogram calibration when libraries are waiting and no calibration exists."""
        mock_db.calibration_state.count.return_value = 0
        mock_db.library_pipeline_states.bulk_transition.return_value = 2

        pipeline_service.trigger_calibration()

        mock_calibration_svc.start_histogram_calibration_background.assert_called_once_with()

    def test_trigger_calibration_existing_calibration(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Existing calibration should shortcut directly into apply dispatch."""
        mock_db.calibration_state.count.return_value = 1
        mock_db.library_pipeline_states.bulk_transition.side_effect = [2, 2]
        mock_dispatch_apply = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_apply", mock_dispatch_apply)

        pipeline_service.trigger_calibration()

        assert mock_db.library_pipeline_states.bulk_transition.call_args_list == [
            ((PIPELINE_AWAITING_CALIBRATION, PIPELINE_CALIBRATING),),
            ((PIPELINE_CALIBRATING, PIPELINE_APPLYING),),
        ]
        mock_dispatch_apply.assert_called_once_with()


class TestOnApplyComplete:
    """Tests for post-apply per-library branching."""

    def test_on_apply_complete_auto_write_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Auto-write libraries with a write mode should dispatch tag writing."""
        library_id = "libraries/lib-auto"
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = [library_id]
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": True,
            "file_write_mode": "id3",
        }
        mock_dispatch_write = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_write", mock_dispatch_write)

        pipeline_service.on_apply_complete()

        mock_db.library_pipeline_states.transition_state.assert_called_once_with(library_id, PIPELINE_WRITING)
        mock_dispatch_write.assert_called_once_with(library_id)

    def test_on_apply_complete_auto_write_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Libraries with auto-write disabled should stop at write_ready."""
        library_id = "libraries/lib-manual"
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = [library_id]
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": False,
            "file_write_mode": "id3",
        }
        mock_dispatch_write = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_write", mock_dispatch_write)

        pipeline_service.on_apply_complete()

        mock_db.library_pipeline_states.transition_state.assert_called_once_with(library_id, PIPELINE_WRITE_READY)
        mock_dispatch_write.assert_not_called()

    def test_on_apply_complete_write_mode_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Libraries configured with write_mode=none should stop at write_ready."""
        library_id = "libraries/lib-none"
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = [library_id]
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": True,
            "file_write_mode": "none",
        }
        mock_dispatch_write = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_write", mock_dispatch_write)

        pipeline_service.on_apply_complete()

        mock_db.library_pipeline_states.transition_state.assert_called_once_with(library_id, PIPELINE_WRITE_READY)
        mock_dispatch_write.assert_not_called()


class TestOnWriteComplete:
    """Tests for final write completion handling."""

    def test_on_write_complete(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_navidrome_svc: MagicMock,
    ) -> None:
        """Write completion should mark the library done and trigger Navidrome rescan."""
        library_id = "libraries/lib-done"

        pipeline_service.on_write_complete(library_id)

        mock_db.library_pipeline_states.transition_state.assert_called_once_with(library_id, PIPELINE_DONE)
        mock_navidrome_svc.trigger_rescan.assert_called_once_with()


class TestRecoverStaleStatesAdditional:
    """Additional tests for stale-state recovery edge branches."""

    def test_recover_stale_states_partial_stale_scanning(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Only stale scanning libraries should transition individually to idle."""
        running_library_id = "libraries/lib-running"
        stale_library_id = "libraries/lib-stale"
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [
            [running_library_id, stale_library_id],
            [],
        ]

        def bulk_transition(from_state: str, to_state: str) -> int:
            return 0

        def get_task_status(task_id: str) -> dict[str, str] | None:
            if task_id == f"scan_library_{running_library_id}":
                return {"status": "running"}
            if task_id == f"scan_library_{stale_library_id}":
                return None
            return {"status": "running"}

        mock_db.library_pipeline_states.bulk_transition.side_effect = bulk_transition
        mock_bts.get_task_status.side_effect = get_task_status

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 1, "calibrating": 0, "applying": 0, "writing": 0}
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            stale_library_id,
            PIPELINE_IDLE,
        )
        assert (PIPELINE_SCANNING, PIPELINE_IDLE) not in [
            call.args for call in mock_db.library_pipeline_states.bulk_transition.call_args_list
        ]
        mock_db.libraries.update_scan_status.assert_called_once_with(
            stale_library_id,
            error="Scan interrupted by server restart",
        )

    def test_recover_stale_states_writing_task_still_running(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Writing libraries with active tasks should remain in writing state."""
        library_id = "libraries/lib-writing"
        mock_db.library_pipeline_states.get_libraries_in_state.side_effect = [[], [library_id]]

        def bulk_transition(from_state: str, to_state: str) -> int:
            return 0

        def get_task_status(task_id: str) -> dict[str, str] | None:
            if task_id == f"write_tags:{library_id}":
                return {"status": "running"}
            return {"status": "running"}

        mock_db.library_pipeline_states.bulk_transition.side_effect = bulk_transition
        mock_bts.get_task_status.side_effect = get_task_status

        result = pipeline_service.recover_stale_states()

        assert result == {"scanning": 0, "calibrating": 0, "applying": 0, "writing": 0}
        mock_db.library_pipeline_states.transition_state.assert_not_called()
        mock_db.libraries.update_scan_status.assert_not_called()


class TestOnCalibrationComplete:
    """Tests for calibration completion orchestration."""

    def test_on_calibration_complete_dispatches_apply(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Calibration completion should transition libraries and dispatch apply."""
        mock_dispatch_apply = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_apply", mock_dispatch_apply)

        pipeline_service.on_calibration_complete()

        mock_db.library_pipeline_states.bulk_transition.assert_called_once_with(
            PIPELINE_CALIBRATING,
            PIPELINE_APPLYING,
        )
        mock_dispatch_apply.assert_called_once_with()


class TestDispatchApply:
    """Tests for calibration apply background dispatch."""

    def test_dispatch_apply_skips_when_already_running(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Should not start a duplicate apply task when apply is already running."""
        mock_tagging_svc.is_apply_running.return_value = True

        pipeline_service._dispatch_apply()

        mock_bts.start_task.assert_not_called()
        mock_tagging_svc._clear_apply_progress.assert_not_called()

    def test_dispatch_apply_starts_task(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Should clear apply state and start a managed BTS task."""
        from nomarr.helpers import ManagedTask

        mock_tagging_svc.is_apply_running.return_value = False

        pipeline_service._dispatch_apply()

        mock_tagging_svc._clear_apply_progress.assert_called_once_with()
        mock_bts.start_task.assert_called_once()
        assert isinstance(mock_bts.start_task.call_args[0][0], ManagedTask)
        assert mock_tagging_svc._apply_result is None
        assert mock_tagging_svc._apply_error is None

    def test_dispatch_apply_handles_bts_value_error(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Duplicate BTS dispatch errors should be swallowed cleanly."""
        mock_tagging_svc.is_apply_running.return_value = False
        mock_bts.start_task.side_effect = ValueError

        pipeline_service._dispatch_apply()

        mock_tagging_svc._clear_apply_progress.assert_called_once_with()
        mock_bts.start_task.assert_called_once()


class TestOnApplyCompleteAdditional:
    """Additional tests for apply completion branching."""

    def test_on_apply_complete_missing_library(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Missing libraries should move to write_ready without write dispatch."""
        library_id = "libraries/lib-missing"
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = [library_id]
        mock_db.libraries.get_library.return_value = None
        mock_dispatch_write = MagicMock()
        monkeypatch.setattr(pipeline_service, "_dispatch_write", mock_dispatch_write)

        pipeline_service.on_apply_complete()

        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            library_id,
            PIPELINE_WRITE_READY,
        )
        mock_dispatch_write.assert_not_called()


class TestDispatchWrite:
    """Tests for write-tags background dispatch."""

    def test_dispatch_write_starts_task(
        self,
        pipeline_service: LibraryPipelineService,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Should start write-tags background work with an event and completion callback."""
        import threading

        library_id = "libraries/lib-write"
        mock_tagging_svc.start_write_tags_background.return_value = "write-task-1"

        pipeline_service._dispatch_write(library_id)

        mock_tagging_svc.start_write_tags_background.assert_called_once()
        args = mock_tagging_svc.start_write_tags_background.call_args.args
        kwargs = mock_tagging_svc.start_write_tags_background.call_args.kwargs
        assert args[0] == library_id
        assert isinstance(args[1], threading.Event)
        assert callable(kwargs["on_complete"])

    def test_dispatch_write_handles_value_error(
        self,
        pipeline_service: LibraryPipelineService,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Duplicate write dispatch errors should be swallowed cleanly."""
        library_id = "libraries/lib-write"
        mock_tagging_svc.start_write_tags_background.side_effect = ValueError

        pipeline_service._dispatch_write(library_id)

        mock_tagging_svc.start_write_tags_background.assert_called_once()


class TestGetPipelineStatus:
    """Tests for per-library pipeline status lookup."""

    def test_get_pipeline_status_returns_none_for_missing_library(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Missing libraries should produce no status DTO."""
        mock_db.libraries.get_library.return_value = None

        result = pipeline_service.get_pipeline_status("libraries/missing")

        assert result is None

    def test_get_pipeline_status_populates_pending_write_count_for_write_ready(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Write-ready libraries should surface the pending write count."""
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": True,
            "file_write_mode": "full",
        }
        mock_db.library_pipeline_states.get_state.return_value = "write_ready"
        mock_tagging_svc.get_reconcile_status.return_value = {"pending_count": 9}

        result = pipeline_service.get_pipeline_status("libraries/test-lib")

        assert result is not None
        assert result.state == "write_ready"
        assert result.pending_write_count == 9
        assert result.untagged_count is None
        assert result.uncalibrated_count is None

    def test_get_pipeline_status_populates_untagged_count_for_ml_running(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """ML-running libraries should surface the untagged file count."""
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": True,
            "file_write_mode": "full",
        }
        mock_db.library_pipeline_states.get_state.return_value = "ml_running"
        mock_db.library_files.count_untagged_files.return_value = 7

        result = pipeline_service.get_pipeline_status("libraries/test-lib")

        assert result is not None
        assert result.state == "ml_running"
        assert result.untagged_count == 7
        assert result.uncalibrated_count is None
        assert result.pending_write_count is None

    def test_get_pipeline_status_populates_uncalibrated_count_for_awaiting_calibration(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Awaiting-calibration libraries should surface the uncalibrated file count."""
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": False,
            "file_write_mode": "minimal",
        }
        mock_db.library_pipeline_states.get_state.return_value = "awaiting_calibration"
        mock_db.library_files.get_uncalibrated_tagged_file_ids.return_value = ["file1", "file2", "file3"]

        result = pipeline_service.get_pipeline_status("libraries/test-lib")

        assert result is not None
        assert result.state == "awaiting_calibration"
        assert result.uncalibrated_count == 3
        assert result.untagged_count is None
        assert result.pending_write_count is None

    def test_get_pipeline_status_populates_pending_write_count_for_writing(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Writing libraries should surface the pending write count."""
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": True,
            "file_write_mode": "full",
        }
        mock_db.library_pipeline_states.get_state.return_value = "writing"
        mock_tagging_svc.get_reconcile_status.return_value = {"pending_count": 4}

        result = pipeline_service.get_pipeline_status("libraries/test-lib")

        assert result is not None
        assert result.state == "writing"
        assert result.pending_write_count == 4
        assert result.untagged_count is None
        assert result.uncalibrated_count is None

    def test_get_pipeline_status_defaults_missing_state_edge_to_idle(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Libraries without a state edge yet should report idle."""
        mock_db.libraries.get_library.return_value = {
            "library_auto_write": False,
            "file_write_mode": "minimal",
        }
        mock_db.library_pipeline_states.get_state.side_effect = ValueError

        result = pipeline_service.get_pipeline_status("libraries/test-lib")

        assert result is not None
        assert result.state == "idle"
        assert result.library_auto_write is False
        assert result.file_write_mode == "minimal"


class TestStopWrite:
    """Tests for reactive write cancellation."""

    def test_stop_write_cancels_bts_task(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
    ) -> None:
        """Stopping a write should cancel the BTS task for that library."""
        pipeline_service.stop_write("libraries/test-lib")

        mock_bts.cancel_task.assert_called_once_with("write_tags:libraries/test-lib")


class TestHandleAutoWrite:
    """Tests for reactive auto-write enable/disable handlers."""

    def test_handle_auto_write_enabled_dispatches_write(
        self,
        pipeline_service: LibraryPipelineService,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """Enabling auto-write should dispatch write-tags background work."""
        library_id = "libraries/test-lib"
        mock_tagging_svc.start_write_tags_background.return_value = "write_tags:libraries/test-lib"

        pipeline_service.handle_auto_write_enabled(library_id)

        mock_tagging_svc.start_write_tags_background.assert_called_once()
        args = mock_tagging_svc.start_write_tags_background.call_args.args
        assert args[0] == library_id

    def test_handle_auto_write_disabled_stops_write(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
    ) -> None:
        """Disabling auto-write should cancel the write-tags BTS task."""
        library_id = "libraries/test-lib"

        pipeline_service.handle_auto_write_disabled(library_id)

        mock_bts.cancel_task.assert_called_once_with("write_tags:libraries/test-lib")


class TestHandleAutoWriteReactive:
    """Tests for auto-write toggle delegation methods."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handle_auto_write_enabled_dispatches_write(
        self,
        pipeline_service: LibraryPipelineService,
    ) -> None:
        """handle_auto_write_enabled should delegate to _dispatch_write."""
        with patch.object(pipeline_service, "_dispatch_write") as mock_dispatch_write:
            pipeline_service.handle_auto_write_enabled("libraries/test-lib")

        mock_dispatch_write.assert_called_once_with("libraries/test-lib")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handle_auto_write_disabled_stops_write(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
    ) -> None:
        """handle_auto_write_disabled should delegate to stop_write."""
        pipeline_service.handle_auto_write_disabled("libraries/test-lib")

        mock_bts.cancel_task.assert_called_once_with("write_tags:libraries/test-lib")
