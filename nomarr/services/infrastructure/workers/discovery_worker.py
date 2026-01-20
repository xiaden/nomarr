"""Discovery-based worker for ML audio processing.

Workers query library_files directly instead of polling a queue.
Each worker claims exactly 1 file at a time using atomic claim documents.

Health telemetry is sent via pipe to parent process (not DB).
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import threading
import time
from multiprocessing import Event
from multiprocessing.synchronize import Event as EventType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessorConfig

logger = logging.getLogger(__name__)

# Worker configuration
HEALTH_FRAME_INTERVAL_S = 5.0  # Send health frame every 5 seconds
IDLE_SLEEP_S = 1.0  # Sleep when no work available
MAX_CONSECUTIVE_ERRORS = 10  # Shutdown after this many consecutive failures

# Health frame prefix
HEALTH_FRAME_PREFIX = "HEALTH|"


class DiscoveryWorker(multiprocessing.Process):
    """Discovery-based ML processing worker.

    Worker loop:
    1. Query library_files for next unprocessed file
    2. Attempt to claim file by inserting claim document
    3. If claim successful, process file using process_file_workflow
    4. Update library_files state (set tagged=1) before removing claim
    5. Repeat immediately (no sleep between files)

    Crash recovery:
    - Worker crashes leave only ephemeral claim documents
    - Claims automatically expire when worker heartbeat goes stale
    - Files with expired claims become available for rediscovery
    """

    def __init__(
        self,
        worker_id: str,
        db_hosts: str,
        db_password: str,
        processor_config_dict: dict[str, Any],
        stop_event: EventType | None = None,
        health_pipe: Any = None,
    ) -> None:
        """Initialize discovery worker.

        Args:
            worker_id: Unique worker identifier (e.g., "worker:tag:0")
            db_hosts: ArangoDB host URL(s)
            db_password: Database password
            processor_config_dict: ProcessorConfig as dict (for multiprocessing)
            stop_event: Event to signal graceful shutdown
            health_pipe: Pipe write-end for health telemetry to parent
        """
        super().__init__()
        self.worker_id = worker_id
        self.db_hosts = db_hosts
        self.db_password = db_password
        self.processor_config_dict = processor_config_dict
        self._stop_event = stop_event or Event()
        self._health_pipe = health_pipe
        self._current_status: str = "pending"  # Current health status for frame emission

    def _send_health_frame(self, status: str) -> None:
        """Send a health frame to the parent process via pipe.

        Args:
            status: Health status (pending, healthy, unhealthy, failed)
        """
        if self._health_pipe is None:
            return

        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": self.worker_id,
                "status": status,
            }
        )
        try:
            self._health_pipe.send(frame)
        except (OSError, BrokenPipeError) as e:
            logger.debug("[%s] Failed to send health frame: %s", self.worker_id, e)

    def _health_writer_loop(self) -> None:
        """Background thread that periodically sends health frames to parent."""
        while not self._stop_event.is_set():
            self._send_health_frame(self._current_status)
            # Sleep in small increments to allow faster shutdown
            for _ in range(int(HEALTH_FRAME_INTERVAL_S * 10)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

    def run(self) -> None:
        """Main worker loop - discover, claim, process, repeat."""
        # Late imports to avoid import-time issues in subprocess
        from nomarr.components.ml.ml_backend_essentia_comp import is_available as ml_is_available
        from nomarr.components.workers.worker_discovery_comp import (
            discover_and_claim_file,
            release_claim,
        )
        from nomarr.helpers.dto.processing_dto import ProcessorConfig
        from nomarr.persistence.db import Database
        from nomarr.workflows.processing.process_file_wf import process_file_workflow

        # Start health writer thread FIRST (sends pending frames via pipe)
        health_thread: threading.Thread | None = None
        if self._health_pipe is not None:
            health_thread = threading.Thread(
                target=self._health_writer_loop,
                daemon=True,
                name=f"HealthWriter-{self.worker_id}",
            )
            health_thread.start()

        # Preflight check: verify ML backend is available
        if not ml_is_available():
            logger.error("[%s] ML backend (Essentia) not available - marking unhealthy", self.worker_id)
            self._current_status = "unhealthy"
            # Keep emitting unhealthy status for a short time, then exit
            time.sleep(10)
            return

        # Create database connection in subprocess
        db = Database(hosts=self.db_hosts, password=self.db_password)

        # Reconstruct ProcessorConfig from dict
        config = ProcessorConfig(**self.processor_config_dict)

        # Mark as healthy now that preflight passed
        self._current_status = "healthy"

        # Register worker in health system (DB - for history/backward compat)
        db.health.mark_starting(self.worker_id, "worker")
        db.health.mark_healthy(self.worker_id)

        logger.info("[%s] Discovery worker started", self.worker_id)

        consecutive_errors = 0
        files_processed = 0

        try:
            while not self._stop_event.is_set():
                # Discover and claim next file
                file_id = discover_and_claim_file(db, self.worker_id)

                if file_id is None:
                    # No work available - sleep briefly
                    time.sleep(IDLE_SLEEP_S)
                    continue

                # Process the claimed file
                try:
                    # Get file path from database
                    file_doc = db.library_files.get_file_by_id(file_id)
                    if not file_doc:
                        logger.warning("[%s] Claimed file %s not found in database", self.worker_id, file_id)
                        release_claim(db, file_id)
                        continue

                    file_path = file_doc["path"]

                    logger.debug("[%s] Processing %s", self.worker_id, file_path)

                    # Run the processing workflow
                    result = process_file_workflow(
                        path=file_path,
                        config=config,
                        db=db,
                    )

                    # Mark file as tagged (this sets needs_tagging=0, tagged=1)
                    db.library_files.mark_file_tagged(file_id, config.tagger_version)

                    # Release claim AFTER marking tagged
                    release_claim(db, file_id)

                    files_processed += 1
                    consecutive_errors = 0

                    logger.debug(
                        "[%s] Completed %s in %.2fs (%d heads, %d tags)",
                        self.worker_id,
                        result.file,
                        result.elapsed,
                        result.heads_processed,
                        result.tags_written,
                    )

                except Exception as e:
                    logger.exception("[%s] Error processing %s: %s", self.worker_id, file_id, e)
                    consecutive_errors += 1

                    # Release claim on error - file becomes rediscoverable
                    release_claim(db, file_id)

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            "[%s] Too many consecutive errors (%d), shutting down",
                            self.worker_id,
                            consecutive_errors,
                        )
                        break

        finally:
            # Cleanup on exit
            logger.info(
                "[%s] Discovery worker stopping (processed %d files)",
                self.worker_id,
                files_processed,
            )
            db.health.mark_stopping(self.worker_id)

            # Close health pipe (this signals EOF to parent reader)
            if self._health_pipe is not None:
                try:
                    self._health_pipe.close()
                except Exception:
                    pass

    def stop(self) -> None:
        """Signal worker to stop gracefully."""
        self._stop_event.set()


def create_discovery_worker(
    worker_index: int,
    db_hosts: str,
    db_password: str,
    processor_config: ProcessorConfig,
    stop_event: EventType | None = None,
    health_pipe: Any = None,
) -> DiscoveryWorker:
    """Factory function to create a DiscoveryWorker.

    Args:
        worker_index: Worker index (0, 1, 2, ...)
        db_hosts: ArangoDB host URL(s)
        db_password: Database password
        processor_config: ProcessorConfig for the processing workflow
        stop_event: Optional shared Event for coordinated shutdown
        health_pipe: Pipe write-end for health telemetry to parent

    Returns:
        Configured DiscoveryWorker process (not started)
    """
    worker_id = f"worker:tag:{worker_index}"

    # Convert ProcessorConfig to dict for multiprocessing serialization
    from dataclasses import asdict

    config_dict = asdict(processor_config)

    return DiscoveryWorker(
        worker_id=worker_id,
        db_hosts=db_hosts,
        db_password=db_password,
        processor_config_dict=config_dict,
        stop_event=stop_event,
        health_pipe=health_pipe,
    )
