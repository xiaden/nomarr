"""Library pipeline orchestration service."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from nomarr.components.library.library_file_state_comp import count_untagged_files, get_uncalibrated_tagged_file_ids
from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.library_scan_state_comp import (
    bulk_transition_pipeline_axis,
    get_libraries_in_axis_state,
    get_pipeline_state,
)
from nomarr.components.library.scan_lifecycle_comp import (
    is_scan_stale,
    transition_pipeline_axis,
    update_scan_progress,
)
from nomarr.helpers import ManagedTask
from nomarr.helpers.constants.pipeline_states import (
    CAL_COMPLETE,
    CAL_IN_PROGRESS,
    CAL_NOT_CALIBRATED,
    CAL_STATE_FIELD,
    ML_IN_PROGRESS,
    ML_STATE_FIELD,
    SCAN_IN_PROGRESS,
    SCAN_NOT_SCANNED,
    SCAN_STATE_FIELD,
    WRITE_COMPLETE,
    WRITE_IN_PROGRESS,
    WRITE_NOT_WRITTEN,
    WRITE_STATE_FIELD,
)
from nomarr.helpers.dto.library_dto import LibraryPipelineStatusDTO
from nomarr.services.domain.calibration_svc import CALIBRATION_GENERATE_TASK_ID, CalibrationService
from nomarr.services.domain.tagging_svc import CALIBRATION_APPLY_TASK_ID, TaggingService

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

logger = logging.getLogger(__name__)


class LibraryPipelineService:
    """Coordinate pipeline state recovery and post-ML orchestration.

    This infrastructure service owns startup recovery and the callback wiring
    between calibration generation, calibration apply, and file writeback.

    Pipeline state is stored as four independent axes on the library document:
    - scan_state: not_scanned / scanning / scanned
    - ml_state: not_ML_processed / ML_processing / ML_processed
    - calibration_state: not_calibrated / calibrating / calibrated
    - tag_write_state: not_written / writing / written
    """

    def __init__(
        self,
        db: Database,
        bts: BackgroundTaskService,
        calibration_svc: CalibrationService,
        tagging_svc: TaggingService,
        navidrome_svc: NavidromeService,
    ) -> None:
        """Initialize the pipeline service with required dependencies.

        Args:
            db: PostgreSQL database instance for state queries.
            bts: Background task service for scheduled work dispatch.
            calibration_svc: Calibration service for histogram generation dispatch.
            tagging_svc: Tagging service for write-background dispatch.
            navidrome_svc: Navidrome service for post-write rescan triggers.

        """
        self.db = db
        self.bts = bts
        self.calibration_svc = calibration_svc
        self.tagging_svc = tagging_svc
        self.navidrome_svc = navidrome_svc

    def recover_stale_states(self) -> dict[str, int]:
        """Recover pipeline states that require missing BTS tasks.

        Per-axis recovery:
        - scan: scanning with no task → not_scanned
        - calibration: calibrating with no task → not_calibrated
        - tag_write: writing with no task → not_written

        Returns:
            Dict with counts per axis: ``{"scanning": int, "calibrating": int,
            "writing": int}``.

        """
        recovery_counts: dict[str, int] = {
            "scanning": 0,
            "calibrating": 0,
            "writing": 0,
        }

        # Recover stale scanning
        scanning_libraries = get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
        stale_scanning = [
            library_id
            for library_id in scanning_libraries
            if not self._is_task_running(self._scan_task_id(int(library_id)))
        ]
        for library_id in stale_scanning:
            transition_pipeline_axis(self.db, library_id, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
            update_scan_progress(
                self.db,
                library_id,
                scan_error="Scan interrupted by server restart",
            )
        recovery_counts["scanning"] = len(stale_scanning)
        if stale_scanning:
            logger.info("Recovered %s stale scanning libraries to not_scanned", len(stale_scanning))

        # Recover stale calibrating
        if not self._is_task_running(CALIBRATION_GENERATE_TASK_ID):
            count = bulk_transition_pipeline_axis(
                self.db,
                CAL_STATE_FIELD,
                CAL_IN_PROGRESS,
                CAL_NOT_CALIBRATED,
            )
            recovery_counts["calibrating"] = count
            if count > 0:
                logger.info("Recovered %s stale calibrating libraries to not_calibrated", count)

        # Recover stale writing
        writing_libraries = get_libraries_in_axis_state(self.db, WRITE_STATE_FIELD, WRITE_IN_PROGRESS)
        for library_id in writing_libraries:
            if self._is_task_running(self._write_task_id(int(library_id))):
                continue
            transition_pipeline_axis(self.db, library_id, WRITE_STATE_FIELD, WRITE_NOT_WRITTEN)
            recovery_counts["writing"] += 1
            logger.info("Recovered stale writing library %s to not_written", library_id)

        return recovery_counts

    def recover_stale_heartbeats(self, timeout_ms: int = 300000) -> int:
        """Recover scanning libraries with stale heartbeats.

        Args:
            timeout_ms: Maximum age of heartbeat in milliseconds before considered stale.
                Defaults to 300000 (5 minutes).

        Returns:
            Number of libraries recovered.

        """
        scanning_libraries = get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
        recovered = 0
        for library_id in scanning_libraries:
            if is_scan_stale(self.db, int(library_id), timeout_ms):
                transition_pipeline_axis(self.db, library_id, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
                update_scan_progress(
                    self.db,
                    library_id,
                    scan_error="Scan timed out: no heartbeat received",
                )
                recovered += 1
                logger.warning(
                    "Recovered scanning library %s due to stale heartbeat",
                    library_id,
                )
        return recovered

    def trigger_calibration(self) -> None:
        """Start calibration for libraries in not_calibrated state.

        If calibration data already exists in the database the axis is advanced
        directly to ``calibrating`` and apply is dispatched.  Otherwise histogram
        calibration generation is started via ``CalibrationService``.
        """
        calibration_exists = len(self.db.ml.list_calibration_states()) > 0
        calibrating_count = bulk_transition_pipeline_axis(
            self.db,
            CAL_STATE_FIELD,
            CAL_NOT_CALIBRATED,
            CAL_IN_PROGRESS,
        )
        if calibrating_count == 0:
            logger.info("No libraries awaiting calibration; skipping calibration trigger")
            return

        if calibration_exists:
            logger.info(
                "Calibration data already exists; transitioned %s libraries to calibrating",
                calibrating_count,
            )
            self._dispatch_apply()
            return

        logger.info(
            "Dispatching histogram calibration generation for %s calibrating libraries",
            calibrating_count,
        )
        self.calibration_svc.start_histogram_calibration_background()

    def on_calibration_complete(self) -> None:
        """Mark calibration axis as complete and dispatch apply.

        Transitions all libraries in ``calibrating`` state to ``calibrated``
        and kicks off the calibration-apply pipeline step.

        This callback is wired to ``CalibrationService.set_post_generation_hook``
        during startup.
        """
        count = bulk_transition_pipeline_axis(
            self.db,
            CAL_STATE_FIELD,
            CAL_IN_PROGRESS,
            CAL_COMPLETE,
        )
        logger.info(
            "Calibration generation completed; transitioned %s libraries to calibrated",
            count,
        )
        self._dispatch_apply()

    def _dispatch_apply(self) -> None:
        """Start calibration apply with a pipeline completion callback."""
        if self.tagging_svc.is_apply_running():
            logger.warning("Calibration apply already running; skipping pipeline dispatch")
            return

        self.tagging_svc._apply_result = None
        self.tagging_svc._apply_error = None
        self.tagging_svc._clear_apply_progress()

        task = ManagedTask(
            task_id=CALIBRATION_APPLY_TASK_ID,
            fn=self.tagging_svc._run_apply_calibration,
            on_complete=lambda: self.on_apply_complete(),
            daemon=False,
        )
        try:
            self.bts.start_task(task)
        except ValueError:
            logger.warning("Calibration apply already running; BTS rejected duplicate dispatch")
            return

        logger.info("Started calibration apply in background via pipeline service")

    def on_apply_complete(self) -> None:
        """After calibration apply, check if auto-write should start."""
        # Find libraries that were calibrating and are now calibrated
        calibrated_libraries = get_libraries_in_axis_state(self.db, CAL_STATE_FIELD, CAL_COMPLETE)
        for library_id in calibrated_libraries:
            state = get_pipeline_state(self.db, int(library_id))
            if state.get(WRITE_STATE_FIELD) == WRITE_IN_PROGRESS:
                continue  # Already writing

            library = get_library_record(self.db, int(library_id), include_scan=False)
            if library is None:
                logger.warning("Library %s was missing during apply completion", library_id)
                continue

            library_auto_write = bool(library.get("library_auto_write", False))
            file_write_mode = str(library.get("file_write_mode", "none"))
            if library_auto_write and file_write_mode != "none":
                transition_pipeline_axis(self.db, library_id, WRITE_STATE_FIELD, WRITE_IN_PROGRESS)
                logger.info(
                    "Library %s entering writing stage after calibration apply completion",
                    library_id,
                )
                self._dispatch_write(int(library_id))
            else:
                logger.info(
                    "Library %s calibrated; tag_write axis stays not_written (auto-write disabled)",
                    library_id,
                )

    def get_pipeline_status(self, library_id: int) -> LibraryPipelineStatusDTO | None:
        """Return state-aware pipeline status details for a library.

        Queries all four pipeline axes (scan, ML, calibration, tag-write) and
        enriches with domain-specific counts (untagged files, uncalibrated tags,
        pending writes).

        Args:
            library_id: Library database ID.

        Returns:
            ``LibraryPipelineStatusDTO`` with per-axis state and optional
            domain counts, or ``None`` if the library does not exist.

        """
        library = get_library_record(self.db, int(library_id), include_scan=False)
        if library is None:
            return None

        state = get_pipeline_state(self.db, int(library_id))

        untagged_count: int | None = None
        uncalibrated_count: int | None = None
        pending_write_count: int | None = None

        if state.get(ML_STATE_FIELD) == ML_IN_PROGRESS:
            untagged_count = count_untagged_files(self.db, int(library_id))
        elif state.get(CAL_STATE_FIELD) in {CAL_NOT_CALIBRATED, CAL_IN_PROGRESS}:
            uncalibrated_count = len(get_uncalibrated_tagged_file_ids(self.db, int(library_id)))
        elif state.get(WRITE_STATE_FIELD) in {WRITE_NOT_WRITTEN, WRITE_IN_PROGRESS}:
            reconcile_status = self.tagging_svc.get_reconcile_status(library_id)
            pending_write_count = int(reconcile_status["pending_count"])

        return LibraryPipelineStatusDTO(
            library_id=int(library_id),
            scan_state=state.get(SCAN_STATE_FIELD, "not_scanned"),
            ml_state=state.get(ML_STATE_FIELD, "not_ML_processed"),
            calibration_state=state.get(CAL_STATE_FIELD, "not_calibrated"),
            tag_write_state=state.get(WRITE_STATE_FIELD, "not_written"),
            untagged_count=untagged_count,
            uncalibrated_count=uncalibrated_count,
            pending_write_count=pending_write_count,
            library_auto_write=bool(library.get("library_auto_write", False)),
            file_write_mode=str(library.get("file_write_mode", "full")),
        )

    def _dispatch_write(self, library_id: int) -> None:
        """Dispatch write-tags background work for a single library."""
        stop_event = threading.Event()
        try:
            task_id = self.tagging_svc.start_write_tags_background(
                library_id,
                stop_event,
                on_complete=lambda: self.on_write_complete(library_id),
            )
        except ValueError:
            logger.warning("Write-tags task already running for library %s", library_id)
            return

        logger.info("Started write-tags task %s for library %s", task_id, library_id)

    def stop_write(self, library_id: int) -> None:
        """Request graceful cancellation of an in-flight write task."""
        task_id = self._write_task_id(library_id)
        cancelled = self.bts.cancel_task(task_id)
        logger.info("Requested stop for write-tags task %s: cancelled=%s", task_id, cancelled)

    def handle_auto_write_enabled(self, library_id: int) -> None:
        """React to auto-write being enabled for a library."""
        self._dispatch_write(library_id)

    def handle_auto_write_disabled(self, library_id: int) -> None:
        """React to auto-write being disabled for a library."""
        self.stop_write(library_id)

    def on_write_complete(self, library_id: int) -> None:
        """Mark tag_write axis as complete and trigger Navidrome rescan."""
        transition_pipeline_axis(self.db, int(library_id), WRITE_STATE_FIELD, WRITE_COMPLETE)
        logger.info("Library %s tag_write axis transitioned to written", library_id)
        rescan_triggered = self.navidrome_svc.trigger_rescan()
        logger.info(
            "Navidrome rescan triggered after write completion for %s: %s",
            library_id,
            rescan_triggered,
        )

    def _is_task_running(self, task_id: str) -> bool:
        """Return whether the given BTS task currently exists and is running."""
        task_status = self.bts.get_task_status(task_id)
        return task_status is not None and task_status.get("status") == "running"

    def _scan_task_id(self, library_id: int) -> str:
        """Build the BTS task identifier used for library scans."""
        return f"scan_library_{library_id}"

    def _write_task_id(self, library_id: int) -> str:
        """Build the BTS task identifier used for tag writing."""
        return f"write_tags:{library_id}"
