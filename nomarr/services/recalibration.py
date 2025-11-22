"""Recalibration service - applies calibration to existing library files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.workers.base import BaseWorker


logger = logging.getLogger(__name__)


class RecalibrationService:
    """Service for recalibrating library files with updated calibration values.

    This service provides methods to queue files for recalibration and monitor
    progress. Recalibration updates tier and mood tags by applying calibration
    to raw scores already stored in the database, without re-running ML inference.
    """

    def __init__(self, database: Database, worker: BaseWorker | None = None):
        """Initialize the recalibration service.

        Args:
            database: Database instance for queue operations
            worker: RecalibrationWorker (BaseWorker) instance (optional, for worker checks)
        """
        self.db = database
        self.worker = worker

    def enqueue_file(self, file_path: str) -> int:
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
        return self.db.calibration.enqueue_calibration(file_path)

    def enqueue_library(self, paths: list[str]) -> int:
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

        count = 0
        for path in paths:
            try:
                self.db.calibration.enqueue_calibration(path)
                count += 1
            except Exception as e:
                logger.error(f"Failed to queue {path}: {e}")

        logger.info(f"Successfully queued {count}/{len(paths)} files")
        return count

    def get_status(self) -> dict[str, int]:
        """Get current recalibration queue status.

        Returns:
            Dictionary with counts: pending, running, done, error
        """
        return self.db.calibration.get_calibration_status()

    def clear_queue(self) -> int:
        """Clear all pending and completed recalibration jobs.

        Returns:
            Number of jobs cleared

        Note:
            Running jobs will complete but be removed from queue
        """
        count = self.db.calibration.clear_calibration_queue()
        logger.info(f"Cleared {count} recalibration jobs from queue")
        return count

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
