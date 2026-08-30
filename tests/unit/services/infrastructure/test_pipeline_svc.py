"""Unit tests for LibraryPipelineService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.constants.pipeline_states import (
    CAL_COMPLETE,
    CAL_IN_PROGRESS,
    CAL_NOT_CALIBRATED,
    CAL_STATE_FIELD,
    SCAN_NOT_SCANNED,
    SCAN_STATE_FIELD,
    WRITE_COMPLETE,
    WRITE_NOT_WRITTEN,
    WRITE_STATE_FIELD,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


def _make_library(name: str = "Test Library", root_path: str = "/music") -> Library:
    """Build a domain ``Library`` (natural identity) for pipeline tests."""
    return Library(name=name, root_path=root_path)


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

    def _get_libraries_in_axis_state(db, axis_field, axis_value):
        return db.library.get_libraries_in_axis_state(axis_field, axis_value)

    def _bulk_transition_pipeline_axis(db, axis_field, from_state, to_state):
        return db.library.bulk_transition_pipeline_axis(axis_field, from_state, to_state)

    def _transition_pipeline_axis(db, library_id, axis_field, axis_value):
        return db.app.upsert_pipeline_state(library_id, axis_field, {"state": axis_value})

    def _get_pipeline_state(db, library_id):
        return db.library.get_pipeline_state(library_id)

    def _count_untagged_files(db, library_id):
        return db.songs.count_untagged_files(library_id)

    def _get_uncalibrated_tagged_song_ids(db, library_id):
        return db.songs.get_uncalibrated_tagged_song_ids(library_id)

    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_libraries_in_axis_state",
        _get_libraries_in_axis_state,
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.bulk_transition_pipeline_axis",
        _bulk_transition_pipeline_axis,
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.transition_pipeline_axis",
        _transition_pipeline_axis,
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_pipeline_state",
        _get_pipeline_state,
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.count_untagged_files",
        _count_untagged_files,
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_uncalibrated_tagged_song_ids",
        _get_uncalibrated_tagged_song_ids,
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
        """Missing scan task should transition scanning libraries to not_scanned."""
        library = _make_library()
        # First call: scanning libraries, Second call: writing libraries
        mock_db.library.get_libraries_in_axis_state.side_effect = [[library], []]
        mock_db.library.bulk_transition_pipeline_axis.return_value = 0

        pipeline_service.recover_stale_states()

        # Should transition scanning library to not_scanned
        mock_db.app.upsert_pipeline_state.assert_any_call(library, SCAN_STATE_FIELD, {"state": SCAN_NOT_SCANNED})

    def test_recover_stale_states_ignores_missing_scan_row(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """A stale pipeline state without a scan row must not block recovery."""
        library = _make_library()
        mock_db.library.get_libraries_in_axis_state.side_effect = [[library], []]
        mock_db.library.bulk_transition_pipeline_axis.return_value = 0
        mock_db.libraries.update_scan_status.side_effect = ValueError("no scan exists")

        recovery_counts = pipeline_service.recover_stale_states()

        assert recovery_counts["scanning"] == 1
        mock_db.app.upsert_pipeline_state.assert_any_call(library, SCAN_STATE_FIELD, {"state": SCAN_NOT_SCANNED})

    def test_recover_stale_states_calibrating(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """Missing calibration task should bulk-transition calibrating libraries to not_calibrated."""
        mock_db.library.get_libraries_in_axis_state.return_value = []
        mock_db.library.bulk_transition_pipeline_axis.return_value = 1

        pipeline_service.recover_stale_states()

        mock_db.library.bulk_transition_pipeline_axis.assert_called_with(
            CAL_STATE_FIELD, CAL_IN_PROGRESS, CAL_NOT_CALIBRATED
        )


class TestTriggerCalibration:
    """Tests for calibration triggering."""

    def test_trigger_calibration_starts_background_task(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
        mock_calibration_svc: MagicMock,
    ) -> None:
        """Triggering calibration should start a background task."""
        mock_db.ml.list_calibration_states = MagicMock(return_value=[])
        mock_db.library.bulk_transition_pipeline_axis.return_value = 1

        pipeline_service.trigger_calibration()

        mock_calibration_svc.start_histogram_calibration_background.assert_called_once()


class TestOnCalibrationComplete:
    """Tests for calibration completion handling."""

    def test_on_calibration_complete_transitions_to_calibrated(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Calibration completion should transition to calibrated."""
        mock_db.library.bulk_transition_pipeline_axis.return_value = 1

        pipeline_service.on_calibration_complete()

        mock_db.library.bulk_transition_pipeline_axis.assert_called_with(CAL_STATE_FIELD, CAL_IN_PROGRESS, CAL_COMPLETE)


class TestOnApplyComplete:
    """Tests for calibration apply completion handling."""

    def test_on_apply_complete_does_not_crash(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Apply completion should not crash."""
        mock_db.library.get_libraries_in_axis_state.return_value = []

        # Should not raise
        pipeline_service.on_apply_complete()

    def test_on_apply_complete_skips_deleted_library(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Apply completion must not dispatch write work for a deleted library."""
        library = _make_library()
        mock_db.library.get_libraries_in_axis_state.return_value = [library]
        mock_db.library.get_library.return_value = None  # library deleted

        pipeline_service.on_apply_complete()

        # No write-axis transition and no write task dispatch.
        mock_db.app.upsert_pipeline_state.assert_not_called()
        pipeline_service.tagging_svc.start_write_tags_background.assert_not_called()


class TestOnWriteComplete:
    """Tests for tag write completion handling."""

    def test_on_write_complete_transitions_to_written(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Write completion should transition to written."""
        library = _make_library()

        pipeline_service.on_write_complete(library)

        mock_db.app.upsert_pipeline_state.assert_called_with(library, WRITE_STATE_FIELD, {"state": WRITE_COMPLETE})

    def test_on_write_complete_rejects_remaining_work(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Write completion must refuse to mark complete while files remain."""
        library = _make_library()

        with pytest.raises(RuntimeError, match="files remain"):
            pipeline_service.on_write_complete(library, remaining=5)

        # The write-complete transition must NOT have been reached.
        mock_db.app.upsert_pipeline_state.assert_not_called()

    def test_on_write_complete_zero_remaining_transitions_to_written(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_navidrome_svc: MagicMock,
    ) -> None:
        """Zero remaining files is the all-done representation and completes."""
        library = _make_library()

        pipeline_service.on_write_complete(library, remaining=0)

        mock_db.app.upsert_pipeline_state.assert_called_with(library, WRITE_STATE_FIELD, {"state": WRITE_COMPLETE})
        mock_navidrome_svc.trigger_rescan.assert_called_once()


class TestDispatchWrite:
    """Tests for the write-tags dispatch completion callback wiring."""

    def test_dispatch_write_on_complete_passes_pending_count(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """The completion callback reads pending_count and passes it through."""
        library = _make_library()
        mock_tagging_svc.get_reconcile_status.return_value = {
            "pending_count": 0,
            "failed_count": 0,
            "in_progress": False,
        }

        pipeline_service._dispatch_write(library)

        on_complete = mock_tagging_svc.start_write_tags_background.call_args.kwargs["on_complete"]
        on_complete()

        mock_tagging_svc.get_reconcile_status.assert_called_once_with(library)
        mock_db.app.upsert_pipeline_state.assert_called_with(library, WRITE_STATE_FIELD, {"state": WRITE_COMPLETE})

    def test_dispatch_write_on_complete_failure_resets_to_not_written(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_tagging_svc: MagicMock,
    ) -> None:
        """A failing completion callback resets the axis before re-raising."""
        library = _make_library()
        mock_tagging_svc.get_reconcile_status.side_effect = RuntimeError("reconcile boom")

        pipeline_service._dispatch_write(library)

        on_complete = mock_tagging_svc.start_write_tags_background.call_args.kwargs["on_complete"]
        with pytest.raises(RuntimeError, match="reconcile boom"):
            on_complete()

        mock_db.app.upsert_pipeline_state.assert_called_with(
            library,
            WRITE_STATE_FIELD,
            {"state": WRITE_NOT_WRITTEN},
        )


class TestStopWrite:
    """Tests for write-task stopping."""

    def test_stop_write_cancels_and_joins_write_task(
        self,
        pipeline_service: LibraryPipelineService,
        mock_bts: MagicMock,
    ) -> None:
        """stop_write should signal and join the write task, not merely signal it."""
        library = _make_library(name="Rock Library")

        pipeline_service.stop_write(library)

        mock_bts.cancel_and_join.assert_called_once_with("write_tags:Rock Library", None)

    @pytest.mark.parametrize(
        ("terminal_status", "expects_reset"),
        [
            ("cancelled", True),
            ("error", True),
            ("complete", False),
            (None, False),
        ],
    )
    def test_stop_write_axis_reset_matrix(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
        terminal_status: str | None,
        expects_reset: bool,
    ) -> None:
        """Only cancelled/error terminal statuses reset the write axis to not_written."""
        library = _make_library(name="Rock Library")
        mock_bts.cancel_and_join.return_value = True
        mock_bts.get_task_status.return_value = (
            {"status": terminal_status, "result": None, "error": None} if terminal_status is not None else None
        )

        pipeline_service.stop_write(library)

        if expects_reset:
            mock_db.app.upsert_pipeline_state.assert_called_with(
                library,
                WRITE_STATE_FIELD,
                {"state": WRITE_NOT_WRITTEN},
            )
        else:
            mock_db.app.upsert_pipeline_state.assert_not_called()

    def test_stop_write_no_reset_when_task_unfinished(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
        mock_bts: MagicMock,
    ) -> None:
        """A task still running after the timeout must not reset the write axis."""
        library = _make_library(name="Rock Library")
        mock_bts.cancel_and_join.return_value = False

        pipeline_service.stop_write(library)

        mock_bts.get_task_status.assert_not_called()
        mock_db.app.upsert_pipeline_state.assert_not_called()
