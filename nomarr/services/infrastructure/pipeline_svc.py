"""Library pipeline orchestration service."""

from __future__ import annotations

import functools
import logging
import threading

from nomarr.components.library.library_file_state_comp import count_untagged_files, get_uncalibrated_tagged_file_ids
from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.scan_lifecycle_comp import (
    bulk_transition_pipeline_state,
    get_libraries_in_pipeline_state,
    get_pipeline_state,
    transition_pipeline_state,
    update_scan_progress,
)
from nomarr.helpers import ManagedTask
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
from nomarr.helpers.dto.library_dto import LibraryPipelineStatusDTO
from nomarr.persistence.db import Database
from nomarr.services.domain.calibration_svc import CALIBRATION_GENERATE_TASK_ID, CalibrationService
from nomarr.services.domain.navidrome_svc import NavidromeService
from nomarr.services.domain.tagging_svc import CALIBRATION_APPLY_TASK_ID, TaggingService
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

logger = logging.getLogger(__name__)


class LibraryPipelineService:
    """Coordinate pipeline state recovery and post-ML orchestration.

    This infrastructure service owns startup recovery and the callback wiring
    between calibration generation, calibration apply, and file writeback.
    """

    def __init__(
        self,
        db: Database,
        bts: BackgroundTaskService,
        calibration_svc: CalibrationService,
        tagging_svc: TaggingService,
        navidrome_svc: NavidromeService,
    ) -> None:
        self.db = db
        self.bts = bts
        self.calibration_svc = calibration_svc
        self.tagging_svc = tagging_svc
        self.navidrome_svc = navidrome_svc

    def recover_stale_states(self) -> dict[str, int]:
        """Recover pipeline states that require missing BTS tasks."""
        recovery_counts: dict[str, int] = {
            "scanning": 0,
            "calibrating": 0,
            "applying": 0,
            "writing": 0,
        }

        scanning_libraries = get_libraries_in_pipeline_state(self.db, PIPELINE_SCANNING)
        stale_scanning = [
            library_id for library_id in scanning_libraries if not self._is_task_running(self._scan_task_id(library_id))
        ]
        if stale_scanning:
            if len(stale_scanning) == len(scanning_libraries):
                recovery_counts["scanning"] = bulk_transition_pipeline_state(
                    self.db,
                    PIPELINE_SCANNING,
                    PIPELINE_IDLE,
                )
                for library_id in stale_scanning:
                    update_scan_progress(
                        self.db,
                        library_id,
                        scan_error="Scan interrupted by server restart",
                    )
            else:
                for library_id in stale_scanning:
                    transition_pipeline_state(self.db, library_id, PIPELINE_IDLE)
                    update_scan_progress(
                        self.db,
                        library_id,
                        scan_error="Scan interrupted by server restart",
                    )
                recovery_counts["scanning"] = len(stale_scanning)
            logger.info(
                "Recovered %s stale scanning libraries to idle",
                recovery_counts["scanning"],
            )

        if not self._is_task_running(CALIBRATION_GENERATE_TASK_ID):
            recovery_counts["calibrating"] = bulk_transition_pipeline_state(
                self.db,
                PIPELINE_CALIBRATING,
                PIPELINE_AWAITING_CALIBRATION,
            )
            if recovery_counts["calibrating"] > 0:
                logger.info(
                    "Recovered %s stale calibrating libraries to awaiting_calibration",
                    recovery_counts["calibrating"],
                )

        if not self._is_task_running(CALIBRATION_APPLY_TASK_ID):
            recovery_counts["applying"] = bulk_transition_pipeline_state(
                self.db,
                PIPELINE_APPLYING,
                PIPELINE_AWAITING_CALIBRATION,
            )
            if recovery_counts["applying"] > 0:
                logger.info(
                    "Recovered %s stale applying libraries to awaiting_calibration",
                    recovery_counts["applying"],
                )

        writing_libraries = get_libraries_in_pipeline_state(self.db, PIPELINE_WRITING)
        for library_id in writing_libraries:
            if self._is_task_running(self._write_task_id(library_id)):
                continue
            transition_pipeline_state(self.db, library_id, PIPELINE_WRITE_READY)
            recovery_counts["writing"] += 1
            logger.info("Recovered stale writing library %s to write_ready", library_id)

        return recovery_counts

    def trigger_calibration(self) -> None:
        """Start calibration or shortcut directly to calibration apply."""
        calibration_exists = self.db.calibration_state.count() > 0
        calibrating_count = bulk_transition_pipeline_state(
            self.db,
            PIPELINE_AWAITING_CALIBRATION,
            PIPELINE_CALIBRATING,
        )
        if calibrating_count == 0:
            logger.info("No libraries awaiting calibration; skipping calibration trigger")
            return

        if calibration_exists:
            applying_count = bulk_transition_pipeline_state(
                self.db,
                PIPELINE_CALIBRATING,
                PIPELINE_APPLYING,
            )
            logger.info(
                "Calibration data already exists; transitioned %s libraries to applying",
                applying_count,
            )
            self._dispatch_apply()
            return

        logger.info(
            "Dispatching histogram calibration generation for %s awaiting libraries",
            calibrating_count,
        )
        self.calibration_svc.start_histogram_calibration_background()

    def on_calibration_complete(self) -> None:
        """Advance all calibrating libraries into the apply stage."""
        applying_count = bulk_transition_pipeline_state(
            self.db,
            PIPELINE_CALIBRATING,
            PIPELINE_APPLYING,
        )
        logger.info(
            "Calibration generation completed; transitioned %s libraries to applying",
            applying_count,
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
            on_complete=self.on_apply_complete,
            daemon=False,
        )
        try:
            self.bts.start_task(task)
        except ValueError:
            logger.warning("Calibration apply already running; BTS rejected duplicate dispatch")
            return

        logger.info("Started calibration apply in background via pipeline service")

    def on_apply_complete(self) -> None:
        """Route libraries from applying to writing or write_ready."""
        applying_libraries = get_libraries_in_pipeline_state(self.db, PIPELINE_APPLYING)
        for library_id in applying_libraries:
            library = get_library_record(self.db, library_id, include_scan=False)
            if library is None:
                logger.warning(
                    "Library %s was missing during apply completion; moving to write_ready",
                    library_id,
                )
                transition_pipeline_state(self.db, library_id, PIPELINE_WRITE_READY)
                continue

            library_auto_write = bool(library.get("library_auto_write", False))
            file_write_mode = str(library.get("file_write_mode", "none"))
            if library_auto_write and file_write_mode != "none":
                transition_pipeline_state(self.db, library_id, PIPELINE_WRITING)
                logger.info(
                    "Library %s entering writing stage after calibration apply completion",
                    library_id,
                )
                self._dispatch_write(library_id)
                continue

            transition_pipeline_state(self.db, library_id, PIPELINE_WRITE_READY)
            logger.info(
                "Library %s moved to write_ready after calibration apply completion",
                library_id,
            )

    def get_pipeline_status(self, library_id: str) -> LibraryPipelineStatusDTO | None:
        """Return state-aware pipeline status details for a library."""
        library = get_library_record(self.db, library_id, include_scan=False)
        if library is None:
            return None

        try:
            state = get_pipeline_state(self.db, library_id)
        except ValueError:
            state = "idle"

        untagged_count: int | None = None
        uncalibrated_count: int | None = None
        pending_write_count: int | None = None

        if state == "ml_running":
            untagged_count = count_untagged_files(self.db, library_id)
        elif state in {"awaiting_calibration", "calibrating", "applying"}:
            uncalibrated_count = len(get_uncalibrated_tagged_file_ids(self.db, library_id))
        elif state in {"write_ready", "writing"}:
            pending_write_count = int(self.tagging_svc.get_reconcile_status(library_id)["pending_count"])

        return LibraryPipelineStatusDTO(
            library_id=library_id,
            state=state,
            untagged_count=untagged_count,
            uncalibrated_count=uncalibrated_count,
            pending_write_count=pending_write_count,
            library_auto_write=bool(library.get("library_auto_write", False)),
            file_write_mode=str(library.get("file_write_mode", "full")),
        )

    def _dispatch_write(self, library_id: str) -> None:
        """Dispatch write-tags background work for a single library."""
        stop_event = threading.Event()
        try:
            task_id = self.tagging_svc.start_write_tags_background(
                library_id,
                stop_event,
                on_complete=functools.partial(self.on_write_complete, library_id),
            )
        except ValueError:
            logger.warning("Write-tags task already running for library %s", library_id)
            return

        logger.info("Started write-tags task %s for library %s", task_id, library_id)

    def stop_write(self, library_id: str) -> None:
        """Request graceful cancellation of an in-flight write task."""
        task_id = self._write_task_id(library_id)
        cancelled = self.bts.cancel_task(task_id)
        logger.info("Requested stop for write-tags task %s: cancelled=%s", task_id, cancelled)

    def handle_auto_write_enabled(self, library_id: str) -> None:
        """React to auto-write being enabled for a library."""
        self._dispatch_write(library_id)

    def handle_auto_write_disabled(self, library_id: str) -> None:
        """React to auto-write being disabled for a library."""
        self.stop_write(library_id)

    def on_write_complete(self, library_id: str) -> None:
        """Mark a library done and trigger Navidrome rescan."""
        transition_pipeline_state(self.db, library_id, PIPELINE_DONE)
        logger.info("Library %s pipeline transitioned to done", library_id)
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

    def _scan_task_id(self, library_id: str) -> str:
        """Build the BTS task identifier used for library scans."""
        return f"scan_library_{library_id}"

    def _write_task_id(self, library_id: str) -> str:
        """Build the BTS task identifier used for tag writing."""
        return f"write_tags:{library_id}"
