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
    WRITE_STATE_FIELD,
)
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

    def _get_library_record(db, library_id, **_kwargs):
        return db.libraries.get_library(library_id)

    def _get_libraries_in_axis_state(db, axis_field, axis_value):
        return db.library.get_libraries_in_axis_state(axis_field, axis_value)

    def _bulk_transition_pipeline_axis(db, axis_field, from_state, to_state):
        return db.library.bulk_transition_pipeline_axis(axis_field, from_state, to_state)

    def _transition_pipeline_axis(db, library_id, axis_field, axis_value):
        return db.library.update_pipeline_axis(library_id, axis_field, axis_value)

    def _get_pipeline_state(db, library_id):
        return db.library.get_pipeline_state(library_id)

    def _count_untagged_files(db, library_id):
        return db.songs.count_untagged_files(library_id)

    def _get_uncalibrated_tagged_file_ids(db, library_id):
        return db.songs.get_uncalibrated_tagged_file_ids(library_id)

    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_library_record",
        _get_library_record,
    )
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
        "nomarr.services.infrastructure.pipeline_svc.get_uncalibrated_tagged_file_ids",
        _get_uncalibrated_tagged_file_ids,
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
        library_id = 1
        # First call: scanning libraries, Second call: writing libraries
        mock_db.library.get_libraries_in_axis_state.side_effect = [[library_id], []]
        mock_db.library.bulk_transition_pipeline_axis.return_value = 0

        pipeline_service.recover_stale_states()

        # Should transition scanning library to not_scanned
        mock_db.library.update_pipeline_axis.assert_any_call(library_id, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)

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


class TestOnWriteComplete:
    """Tests for tag write completion handling."""

    def test_on_write_complete_transitions_to_written(
        self,
        pipeline_service: LibraryPipelineService,
        mock_db: MagicMock,
    ) -> None:
        """Write completion should transition to written."""
        library_id = 1

        pipeline_service.on_write_complete(library_id)

        mock_db.library.update_pipeline_axis.assert_called_with(library_id, WRITE_STATE_FIELD, WRITE_COMPLETE)
