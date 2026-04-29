"""Calibration apply lifecycle operations for TaggingService."""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
from nomarr.workflows.calibration.apply_calibration_wf import apply_calibration_wf
from nomarr.workflows.calibration.get_calibration_status_wf import get_calibration_status_workflow
from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf

from .config import (
    CALIBRATION_APPLY_TASK_ID,
    ApplyCalibrationCombinedStatusDict,
    ApplyCalibrationProgressDict,
    ApplyCalibrationResultDict,
    ApplyCalibrationStatusDict,
    TaggingServiceConfig,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
    from nomarr.services.infrastructure.config_svc import ConfigService


logger = logging.getLogger(__name__)


class TaggingApplyMixin:
    """Mixin providing calibration application lifecycle methods."""

    db: Database
    cfg: TaggingServiceConfig
    _bts: BackgroundTaskService
    _config_service: ConfigService
    library_service: LibraryService | None
    _apply_result: ApplyCalibrationResult | None
    _apply_error: Exception | None
    _apply_progress_lock: threading.Lock
    _apply_progress: dict[str, Any]

    def tag_file(self, file_path: str) -> None:
        """Write calibrated tags to a single file.

        Args:
            file_path: Absolute path to the audio file

        """
        params = WriteCalibratedTagsParams(
            file_path=file_path,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self._config_service.get("calibrate_heads", False),
        )

        write_calibrated_tags_wf(db=self.db, params=params)
        logger.info(f"Wrote calibrated tags: {file_path}")

    def tag_library(self) -> ApplyCalibrationResult:
        """Apply calibration to all tagged library files that need it.

        Only processes files whose DB mood tags are stale relative to the
        current calibration version (``meta.calibration_version``). Files
        whose ``calibration_hash`` already matches are skipped, making this
        operation idempotent.

        When no calibration version exists (first run), all tagged files are
        processed so they receive their initial mood tags.

        Delegates to apply_calibration_wf for the actual iteration.
        Progress updates are forwarded via self._update_apply_progress.

        Returns:
            ApplyCalibrationResult with processed/failed counts

        Raises:
            ValueError: If library_service not configured

        """
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot get library paths."
            raise ValueError(msg)

        paths = self.library_service.get_paths_needing_calibration()
        if paths:
            logger.info(f"[TaggingService] {len(paths)} files need calibration update")
        else:
            logger.info("[TaggingService] All tagged files are already calibrated")

        return apply_calibration_wf(
            db=self.db,
            paths=paths,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self._config_service.get("calibrate_heads", False),
            on_progress=self._update_apply_progress,
        )

    def start_apply_calibration_background(self) -> None:
        """Start calibration apply in a managed background task.

        Non-blocking: returns immediately. Poll with is_apply_running() and
        get_apply_combined_status().

        Uses configuration from TaggingServiceConfig for models_dir, namespace, etc.

        Note: Single-process only. Thread state is in-memory and will not survive
        worker restarts, multiple uvicorn workers, or horizontal scaling.

        """
        if self.is_apply_running():
            logger.warning("[TaggingService] Apply already running")
            return

        self._apply_result = None
        self._apply_error = None
        self._clear_apply_progress()

        task = ManagedTask(
            task_id=CALIBRATION_APPLY_TASK_ID,
            fn=self._run_apply_calibration,
            daemon=False,
        )
        try:
            self._bts.start_task(task)
        except ValueError:
            logger.warning("[TaggingService] Apply already running")
            return

        logger.info("[TaggingService] Started calibration apply in background")

    def _run_apply_calibration(self) -> ApplyCalibrationResult:
        """Managed background task: run calibration apply.

        Progress is NOT cleared on completion — the final snapshot remains queryable
        until the next run starts.
        """
        try:
            logger.info("[TaggingService] Background apply started")
            result = self.tag_library()
            self._apply_result = result
            logger.info(
                f"[TaggingService] Background apply completed: "
                f"{result.processed} processed, {result.failed} failed out of {result.total}",
            )
            return result
        except Exception as e:
            logger.error(f"[TaggingService] Background apply failed: {e}", exc_info=True)
            self._apply_error = e
            raise

    def _update_apply_progress(self, **kwargs: int | str | None) -> None:
        """Thread-safe update of apply progress state.

        Args:
            **kwargs: Progress fields to update. Valid keys:
                completed_files, total_files, current_file

        """
        with self._apply_progress_lock:
            self._apply_progress.update(kwargs)

    def _clear_apply_progress(self) -> None:
        """Reset apply progress state."""
        with self._apply_progress_lock:
            self._apply_progress = {}

    def is_apply_running(self) -> bool:
        """Check if calibration apply is currently running."""
        status = self._bts.get_task_status(CALIBRATION_APPLY_TASK_ID)
        return status is not None and status.get("status") == "running"

    def _get_apply_status(self) -> ApplyCalibrationStatusDict:
        """Get current lifecycle status of background calibration apply.

        Lifecycle: idle → running → completed | failed.
        Status remains queryable after completion until next start clears it.

        Returns:
            {
              "status": "idle" | "running" | "completed" | "failed",
              "result": {"processed": int, "failed": int, "total": int, "message": str} | None,
              "error": str | None,
            }

        """
        running = self.is_apply_running()

        status: Literal["idle", "running", "completed", "failed"]
        if running:
            status = "running"
        elif self._apply_error:
            status = "failed"
        elif self._apply_result:
            status = "completed"
        else:
            status = "idle"

        error = str(self._apply_error) if self._apply_error else None
        result_dict: ApplyCalibrationResultDict | None = None
        if self._apply_result:
            result_dict = {
                "processed": self._apply_result.processed,
                "failed": self._apply_result.failed,
                "total": self._apply_result.total,
                "message": self._apply_result.message,
            }

        return {
            "status": status,
            "result": result_dict,
            "error": error,
        }

    def _get_apply_progress(self) -> ApplyCalibrationProgressDict:
        """Get calibration apply progress.

        Progress snapshot persists after completion until next run.

        Returns:
            {
              "total_files": int,
              "completed_files": int,
              "current_file": str | None,
              "is_running": bool,
            }

        """
        running = self.is_apply_running()
        with self._apply_progress_lock:
            progress = dict(self._apply_progress)

        return {
            "total_files": progress.get("total_files", 0),
            "completed_files": progress.get("completed_files", 0),
            "current_file": progress.get("current_file"),
            "is_running": running,
        }

    def get_apply_combined_status(self) -> ApplyCalibrationCombinedStatusDict:
        """Get combined lifecycle status and per-file progress for apply."""
        status = self._get_apply_status()
        progress = self._get_apply_progress()

        return {
            "status": status["status"],
            "result": status["result"],
            "error": status["error"],
            "total_files": progress["total_files"],
            "completed_files": progress["completed_files"],
            "current_file": progress["current_file"],
            "is_running": progress["is_running"],
        }

    def get_calibration_status(self) -> dict[str, Any]:
        """Get global calibration status with per-library breakdown.

        Returns:
            Dict representation of GlobalCalibrationStatus DTO

        """
        result = get_calibration_status_workflow(db=self.db)
        result_dict: dict[str, Any] = asdict(result)
        return result_dict
