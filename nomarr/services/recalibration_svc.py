"""Recalibration service - applies calibration to existing library files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.queue import enqueue_file, get_queue_stats
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult, ClearCalibrationQueueResult, GetStatusResult
from nomarr.workflows.queue import clear_all_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.library_svc import LibraryService
    from nomarr.services.workers.base import BaseWorker


logger = logging.getLogger(__name__)


class RecalibrationService:
    """Service for recalibrating library files with updated calibration values.

    This service provides methods to queue files for recalibration and monitor
    progress. Recalibration updates tier and mood tags by applying calibration
    to raw scores already stored in the database, without re-running ML inference.
    """

    def __init__(
        self, database: Database, worker: BaseWorker | None = None, library_service: LibraryService | None = None
    ):
        """Initialize the recalibration service.

        Args:
            database: Database instance for queue operations
            worker: RecalibrationWorker (BaseWorker) instance (optional, for worker checks)
            library_service: LibraryService instance (optional, for library operations)
        """
        self.db = database
        self.worker = worker
        self.library_service = library_service

    def enqueue_file_for_recalibration(self, file_path: str) -> int:
        """Queue a single file for recalibration.

        Args:
            file_path: Absolute path to the audio file

        Returns:
            Job ID for the queued recalibration

        Raises:
            RuntimeError: If worker is not available
        """
        if self.worker is None or not self.worker.is_alive():
            raise RuntimeError("RecalibrationWorker is not available. Cannot queue recalibration jobs.")

        logger.info(f"Queuing recalibration for: {file_path}")
        return enqueue_file(self.db, file_path, force=False, queue_type="calibration")

    def enqueue_library_for_recalibration(self, paths: list[str]) -> int:
        """Queue multiple library files for recalibration.

        Args:
            paths: List of absolute file paths to recalibrate

        Returns:
            Number of files queued

        Raises:
            RuntimeError: If worker is not available
            ValueError: If paths list is empty
        """
        if not paths:
            raise ValueError("Cannot enqueue empty list of files")

        if self.worker is None or not self.worker.is_alive():
            raise RuntimeError("RecalibrationWorker is not available. Cannot queue recalibration jobs.")

        logger.info(f"Queuing {len(paths)} files for recalibration")

        queued_count = 0
        for file_path in paths:
            try:
                enqueue_file(self.db, file_path, force=False, queue_type="calibration")
                queued_count += 1
            except Exception as e:
                logger.warning(f"Failed to enqueue {file_path}: {e}")

        logger.info(f"Successfully queued {queued_count}/{len(paths)} files")
        return queued_count

    def get_status(self) -> GetStatusResult:
        """Get current recalibration queue status.

        Returns:
            GetStatusResult with counts for pending, running, done, error
        """
        status_dict = get_queue_stats(self.db, queue_type="calibration")
        return GetStatusResult(
            pending=status_dict["pending"],
            running=status_dict["running"],
            done=status_dict["done"],
            error=status_dict["error"],
        )

    def get_status_with_worker_state(self) -> tuple[GetStatusResult, bool, bool]:
        """Get status with worker alive/busy state.

        Returns:
            Tuple of (status, worker_alive, worker_busy)
        """
        status = self.get_status()
        worker_alive = self.is_worker_alive()
        worker_busy = self.is_worker_busy()
        return (status, worker_alive, worker_busy)

    def clear_queue(self) -> int:
        """Clear all pending and completed recalibration jobs.

        Returns:
            Number of jobs cleared

        Note:
            Running jobs will complete but be removed from queue
        """
        count = clear_all_workflow(self.db, queue_type="calibration")
        logger.info(f"Cleared {count} recalibration jobs from queue")
        return count

    def clear_queue_with_result(self) -> ClearCalibrationQueueResult:
        """Clear all pending and completed recalibration jobs with result DTO.

        Returns:
            ClearCalibrationQueueResult with count and message

        Note:
            Running jobs will complete but be removed from queue
        """
        count = self.clear_queue()
        return ClearCalibrationQueueResult(
            cleared=count,
            message=f"Cleared {count} jobs from calibration queue",
        )

    def is_worker_alive(self) -> bool:
        """Check if the recalibration worker is running.

        Returns:
            True if worker is alive and processing jobs
        """
        return self.worker is not None and self.worker.is_alive()

    def is_worker_busy(self) -> bool:
        """Check if the recalibration worker is currently processing a file.

        Returns:
            True if worker is busy processing
        """
        return self.worker is not None and self.worker.is_busy()

    def queue_library_for_recalibration(self) -> ApplyCalibrationResult:
        """Queue all library files for recalibration.

        This is a consolidated service method that:
        1. Gets all library paths from library_service
        2. Enqueues them for recalibration
        3. Returns a result DTO

        Returns:
            ApplyCalibrationResult with queued count and message

        Raises:
            ValueError: If library_service not configured
            RuntimeError: If worker not available
        """
        if self.library_service is None:
            raise ValueError("LibraryService not configured. Cannot get library paths.")

        # Get all library file paths
        paths = self.library_service.get_all_library_paths()

        if not paths:
            return ApplyCalibrationResult(queued=0, message="No library files found")

        # Enqueue all files
        count = self.enqueue_library_for_recalibration(paths)

        return ApplyCalibrationResult(queued=count, message=f"Queued {count} files for recalibration")
