"""
RecalibrationWorker - Apply calibration to existing library tags.

This worker:
1. Polls calibration_queue for pending files
2. Delegates to recalibration workflow for processing
3. Updates job status in database
4. Skips ML inference entirely (workflow uses existing DB data)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from nomarr.workflows.recalibrate_file import recalibrate_file_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class RecalibrationWorker(threading.Thread):
    """
    Background worker that applies calibration to library files.

    Reads raw tags from DB, applies calibration, updates files.
    Much faster than retagging since no ML inference is needed.
    """

    def __init__(
        self,
        db: Database,
        models_dir: str,
        namespace: str = "nom",
        version_tag_key: str = "nom_version",
        poll_interval: int = 2,
        calibrate_heads: bool = False,
    ):
        """
        Initialize recalibration worker.

        Args:
            db: Database instance
            models_dir: Path to models directory (for loading calibration sidecars)
            namespace: Tag namespace (default: "nom")
            version_tag_key: Tag key used for version identification (default: "nom_version")
            poll_interval: Seconds between queue polls (default: 2)
            calibrate_heads: If True, use versioned calibration files (dev mode)
        """
        super().__init__(daemon=True, name="RecalibrationWorker")
        self.db = db
        self.models_dir = models_dir
        self.namespace = namespace
        self.version_tag_key = version_tag_key
        self.poll_interval = max(1, poll_interval)
        self.calibrate_heads = calibrate_heads

        # Worker state
        self._stop_event = threading.Event()
        self._shutdown = False
        self._is_busy = False
        self._last_heartbeat = 0

    # ---------------------------- Control Methods ----------------------------

    def stop(self) -> None:
        """Signal worker to stop gracefully."""
        logging.info("[RecalibrationWorker] Stop requested")
        self._shutdown = True
        self._stop_event.set()

    def is_alive_check(self) -> bool:
        """Check if worker thread is alive and healthy."""
        return self.is_alive()

    def is_busy(self) -> bool:
        """Check if worker is currently processing a file."""
        return self._is_busy

    # ---------------------------- Worker Loop ----------------------------

    def run(self) -> None:
        """Main worker loop - poll queue and process jobs."""
        logging.info(f"[RecalibrationWorker] Started (poll_interval={self.poll_interval}s)")

        # Reset any stuck running jobs on startup
        reset_count = self.db.calibration.reset_running_calibration_jobs()
        if reset_count > 0:
            logging.info(f"[RecalibrationWorker] Reset {reset_count} stuck running jobs to pending")

        while not self._shutdown:
            try:
                self._heartbeat()

                # Get next pending job
                job = self.db.calibration.get_next_calibration_job()
                if not job:
                    # No jobs - sleep and continue
                    self._stop_event.wait(self.poll_interval)
                    continue

                job_id, file_path = job
                self._is_busy = True

                try:
                    # Process the recalibration job
                    self._recalibrate_file(job_id, file_path)
                    self.db.calibration.complete_calibration_job(job_id)
                    logging.info(f"[RecalibrationWorker] Completed: {file_path}")

                except Exception as e:
                    error_message = str(e)
                    self.db.calibration.fail_calibration_job(job_id, error_message)
                    logging.error(f"[RecalibrationWorker] Failed {file_path}: {error_message}")

                finally:
                    self._is_busy = False

            except Exception as e:
                logging.error(f"[RecalibrationWorker] Unexpected error in worker loop: {e}")
                time.sleep(self.poll_interval)

        logging.info("[RecalibrationWorker] Stopped")

    def _recalibrate_file(self, job_id: int, file_path: str) -> None:
        """
        Recalibrate a single file by delegating to workflow.

        Args:
            job_id: Calibration job ID (for logging/tracking)
            file_path: Absolute path to audio file
        """
        logging.debug(f"[RecalibrationWorker] Processing job {job_id}: {file_path}")

        # Delegate to workflow
        recalibrate_file_workflow(
            db=self.db,
            file_path=file_path,
            models_dir=self.models_dir,
            namespace=self.namespace,
            version_tag_key=self.version_tag_key,
            calibrate_heads=self.calibrate_heads,
        )

    def _heartbeat(self) -> None:
        """Update heartbeat timestamp."""
        self._last_heartbeat = int(time.time())
