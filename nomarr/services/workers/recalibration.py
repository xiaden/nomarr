"""
RecalibrationWorker - Apply calibration to existing library tags.

This worker:
1. Polls calibration_queue for pending files
2. Loads raw tag scores from library_tags table
3. Applies calibration to scores
4. Writes updated tier and mood tags to files
5. Skips ML inference entirely (uses existing DB data)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.data.db import Database


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
        poll_interval: int = 2,
    ):
        """
        Initialize recalibration worker.

        Args:
            db: Database instance
            models_dir: Path to models directory (for loading calibration sidecars)
            namespace: Tag namespace (default: "nom")
            poll_interval: Seconds between queue polls (default: 2)
        """
        super().__init__(daemon=True, name="RecalibrationWorker")
        self.db = db
        self.models_dir = models_dir
        self.namespace = namespace
        self.poll_interval = max(1, poll_interval)

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
        reset_count = self.db.reset_running_calibration_jobs()
        if reset_count > 0:
            logging.info(f"[RecalibrationWorker] Reset {reset_count} stuck running jobs to pending")

        while not self._shutdown:
            try:
                self._heartbeat()

                # Get next pending job
                job = self.db.get_next_calibration_job()
                if not job:
                    # No jobs - sleep and continue
                    self._stop_event.wait(self.poll_interval)
                    continue

                job_id, file_path = job
                self._is_busy = True

                try:
                    # Process the recalibration job
                    self._recalibrate_file(job_id, file_path)
                    self.db.complete_calibration_job(job_id)
                    logging.info(f"[RecalibrationWorker] Completed: {file_path}")

                except Exception as e:
                    error_msg = str(e)
                    self.db.fail_calibration_job(job_id, error_msg)
                    logging.error(f"[RecalibrationWorker] Failed {file_path}: {error_msg}")

                finally:
                    self._is_busy = False

            except Exception as e:
                logging.error(f"[RecalibrationWorker] Unexpected error in worker loop: {e}")
                time.sleep(self.poll_interval)

        logging.info("[RecalibrationWorker] Stopped")

    def _recalibrate_file(self, job_id: int, file_path: str) -> None:
        """
        Recalibrate a single file.

        Loads raw tags from DB, applies calibration, writes updated tags to file.

        Args:
            job_id: Calibration job ID
            file_path: Absolute path to audio file
        """
        import json

        from nomarr.tagging.aggregation import aggregate_mood_tiers, load_calibrations
        from nomarr.tagging.writer import TagWriter

        logging.debug(f"[RecalibrationWorker] Processing {file_path}")

        # Load calibrations from models directory
        calibrations = load_calibrations(self.models_dir)

        # Get file from library
        library_file = self.db.get_library_file(file_path)
        if not library_file:
            raise FileNotFoundError(f"File not in library: {file_path}")

        file_id = library_file["id"]

        # Get all raw tags for this file from library_tags
        cursor = self.db.conn.execute(
            "SELECT tag_key, tag_value, tag_type FROM library_tags WHERE file_id = ?",
            (file_id,),
        )

        raw_tags = {}
        for tag_key, tag_value, tag_type in cursor.fetchall():
            # Only process namespace tags
            if not tag_key.startswith(f"{self.namespace}:"):
                continue

            # Parse value based on type
            if tag_type == "array":
                raw_tags[tag_key] = json.loads(tag_value)
            elif tag_type == "float":
                raw_tags[tag_key] = float(tag_value)
            elif tag_type == "int":
                raw_tags[tag_key] = int(tag_value)
            else:
                raw_tags[tag_key] = tag_value

        if not raw_tags:
            logging.warning(f"[RecalibrationWorker] No raw tags found for {file_path}")
            return

        # Apply calibration and regenerate mood tiers
        # Note: aggregate_mood_tiers mutates tags dict in-place, doesn't return anything
        aggregate_mood_tiers(raw_tags, calibrations=calibrations)

        # Only update tier and mood aggregation tags in the file
        # (Keep all raw score tags unchanged)
        tier_and_mood_keys = {
            f"{self.namespace}:mood-strict",
            f"{self.namespace}:mood-regular",
            f"{self.namespace}:mood-loose",
        }

        # Add all *_tier tags
        for key in raw_tags:
            if key.endswith("_tier"):
                tier_and_mood_keys.add(key)

        # Filter to only tier/mood tags
        tags_to_update = {k: v for k, v in raw_tags.items() if k in tier_and_mood_keys}

        if not tags_to_update:
            logging.debug(f"[RecalibrationWorker] No tier tags to update for {file_path}")
            return

        # Strip namespace prefix from keys for TagWriter
        # TagWriter expects keys without namespace (it adds it internally)
        tags_without_namespace = {}
        for key, value in tags_to_update.items():
            # Remove 'namespace:' prefix
            if key.startswith(f"{self.namespace}:"):
                clean_key = key[len(self.namespace) + 1 :]
                tags_without_namespace[clean_key] = value

        # Write updated tags to file using TagWriter (handles all formats)
        writer = TagWriter(overwrite=True, namespace=self.namespace)
        writer.write(file_path, tags_without_namespace)

    def _heartbeat(self) -> None:
        """Update heartbeat timestamp."""
        self._last_heartbeat = int(time.time())
