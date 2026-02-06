"""Discovery-based worker for ML audio processing.

Workers query library_files directly instead of polling a queue.
Each worker claims exactly 1 file at a time using atomic claim documents.

Health telemetry is sent via pipe to parent process (not DB).
"""

from __future__ import annotations

import contextlib
import json
import logging
import multiprocessing
import threading
import time
from multiprocessing import Event
from typing import TYPE_CHECKING, Any

from nomarr.helpers.time_helper import internal_s

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event as EventType

    from nomarr.helpers.dto.processing_dto import ProcessorConfig

logger = logging.getLogger(__name__)

# Worker configuration
HEALTH_FRAME_INTERVAL_S = 3.0  # Send health frame every 3 seconds (faster than 5s staleness check)
IDLE_SLEEP_S = 1.0  # Sleep when no work available
MAX_CONSECUTIVE_ERRORS = 10  # Shutdown after this many consecutive failures
CACHE_IDLE_TIMEOUT_S = 300  # Evict cache after 5 minutes of no work (matches default)

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
        execution_tier: int = 0,
        prefer_gpu: bool = True,
    ) -> None:
        """Initialize discovery worker.

        Args:
            worker_id: Unique worker identifier (e.g., "worker:tag:0")
            db_hosts: ArangoDB host URL(s)
            db_password: Database password
            processor_config_dict: ProcessorConfig as dict (for multiprocessing)
            stop_event: Event to signal graceful shutdown
            health_pipe: Pipe write-end for health telemetry to parent
            execution_tier: Execution tier (0-4) from admission control
            prefer_gpu: Whether to prefer GPU for backbone execution

        """
        super().__init__()
        self.worker_id = worker_id
        self.db_hosts = db_hosts
        self.db_password = db_password
        self.processor_config_dict = processor_config_dict
        self._stop_event = stop_event or Event()
        self._health_pipe = health_pipe
        self._current_status: str = "pending"  # Current health status for frame emission
        self.execution_tier = execution_tier  # GPU/CPU tier from admission control
        self.prefer_gpu = prefer_gpu  # GPU preference from tier config

    def _configure_subprocess_logging(self) -> None:
        """Configure logging for the subprocess.

        When using multiprocessing with 'spawn' start method, subprocesses
        don't inherit the parent's logging configuration. This method sets up
        logging handlers that match the main process format, writing to both
        console and rotating file.
        """
        import logging.handlers
        import sys
        from pathlib import Path

        from nomarr.helpers.logging_helper import NomarrLogFilter

        # Same format as start.py
        log_format = "%(asctime)s %(levelname)s %(nomarr_identity_tag)s %(nomarr_role_tag)s%(context_str)s%(message)s"

        # Create logs directory if needed
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Create rotating file handler (same settings as start.py)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "nomarr.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(log_format))
        file_handler.addFilter(NomarrLogFilter())  # Filter must be on handler for subprocess

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(log_format))
        console_handler.addFilter(NomarrLogFilter())  # Filter must be on handler for subprocess

        # Configure root logger first (force=True clears existing config including filters)
        logging.basicConfig(
            level=logging.INFO,
            handlers=[file_handler, console_handler],
            force=True,  # Override any existing config
        )

        logger.info("[%s] Subprocess logging configured", self.worker_id)

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
            },
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
        # Configure logging for subprocess (spawn doesn't inherit parent's logging config)
        self._configure_subprocess_logging()

        # Late imports to avoid import-time issues in subprocess
        from nomarr.components.ml.ml_backend_essentia_comp import is_available as ml_is_available
        from nomarr.components.platform.resource_monitor_comp import check_resource_headroom
        from nomarr.components.workers.worker_discovery_comp import (
            discover_and_claim_file,
            release_claim,
        )
        from nomarr.helpers.dto.processing_dto import ProcessorConfig, ResourceManagementConfig
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

        # Get resource management config (may be None if disabled)
        rm_config: ResourceManagementConfig | None = config.resource_management

        # Mark as healthy now that preflight passed
        self._current_status = "healthy"

        # Register worker in health system (DB - for history/backward compat)
        db.health.mark_starting(self.worker_id, "worker")
        db.health.mark_healthy(self.worker_id)

        logger.info(
            "[%s] Discovery worker started (tier=%d, prefer_gpu=%s)",
            self.worker_id,
            self.execution_tier,
            self.prefer_gpu,
        )

        consecutive_errors = 0
        files_processed = 0
        cache_warmed = False  # Lazy cache warmup - only warm when work arrives
        recovering_until: float | None = None  # Recovery deadline if in recovering state

        try:
            while not self._stop_event.is_set():
                # Check if in recovery state
                if recovering_until is not None:
                    if internal_s().value < recovering_until:
                        # Still recovering - sleep briefly and recheck
                        time.sleep(1.0)
                        continue
                    # Recovery window expired - check resources again
                    recovering_until = None
                    self._current_status = "healthy"
                    logger.info("[%s] Recovery window expired, resuming work", self.worker_id)

                # Discover and claim next file
                logger.debug("[%s] Polling for work...", self.worker_id)
                file_id = discover_and_claim_file(db, self.worker_id)

                if file_id is None:
                    logger.debug("[%s] No work found, sleeping %.1fs", self.worker_id, IDLE_SLEEP_S)
                    # No work available - check for cache eviction (idle timeout)
                    from nomarr.components.ml.ml_cache_comp import check_and_evict_idle_cache

                    if check_and_evict_idle_cache():
                        cache_warmed = False  # Cache was evicted, will need re-warmup
                        logger.info("[%s] ML cache evicted due to idle timeout", self.worker_id)

                    time.sleep(IDLE_SLEEP_S)
                    continue

                logger.debug("[%s] Work found: claimed file %s", self.worker_id, file_id)

                # Per-file resource check (GPU_REFACTOR_PLAN.md Section 11)
                # Only if resource management is enabled
                if rm_config is not None and rm_config.enabled:
                    resource_status = check_resource_headroom(
                        vram_budget_mb=rm_config.vram_budget_mb,
                        ram_budget_mb=rm_config.ram_budget_mb,
                        vram_estimate_mb=8192,  # Conservative backbone estimate
                        ram_estimate_mb=2048,  # Conservative heads estimate
                        ram_detection_mode=rm_config.ram_detection_mode,
                    )

                    # Check resource headroom
                    if not resource_status.vram_ok and not resource_status.ram_ok:
                        # Both VRAM and RAM exhausted - enter recovering state
                        # Per GPU_REFACTOR_PLAN.md Section 12: release claim, report recovering
                        logger.warning(
                            "[%s] Resources exhausted (VRAM=%dMB, RAM=%dMB) - entering recovery",
                            self.worker_id,
                            resource_status.vram_used_mb,
                            resource_status.ram_used_mb,
                        )
                        release_claim(db, file_id)
                        self._current_status = "recovering"
                        recovering_until = internal_s().value + 30.0  # 30s recovery window
                        continue

                    # If only VRAM exhausted but RAM OK, we can still process (CPU spill)
                    # The prefer_gpu setting from tier selection still applies
                    if not resource_status.vram_ok and resource_status.ram_ok:
                        logger.info(
                            "[%s] VRAM pressure, spilling to CPU (RAM=%dMB available)",
                            self.worker_id,
                            resource_status.ram_used_mb,
                        )

                # Lazy cache warmup: warm cache on first file discovered
                # This avoids VRAM allocation until actual work arrives
                if not cache_warmed:
                    from nomarr.components.ml.ml_cache_comp import is_initialized, warmup_predictor_cache

                    if not is_initialized():
                        logger.info("[%s] Work discovered - warming up ML cache...", self.worker_id)
                        try:
                            count = warmup_predictor_cache(
                                models_dir=config.models_dir,
                                cache_idle_timeout=CACHE_IDLE_TIMEOUT_S,
                            )
                            logger.info("[%s] ML cache ready: %d predictors loaded", self.worker_id, count)
                        except Exception as e:
                            logger.exception("[%s] Failed to warm ML cache: %s", self.worker_id, e)
                            # Continue anyway - workflow will create predictors inline (slower but works)
                    cache_warmed = True

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

                    # Check if file was skipped (e.g., audio too short)
                    if result.heads_processed == 0 and result.tags_written == 0:
                        # File was skipped - mark as tagged with special reason to avoid infinite retries
                        logger.info(
                            "[%s] Skipped %s (all heads skipped - likely too short)",
                            self.worker_id,
                            file_path,
                        )
                        # Mark as tagged so it doesn't get retried
                        db.library_files.mark_file_tagged(file_id, config.tagger_version)
                        release_claim(db, file_id)
                        files_processed += 1
                        consecutive_errors = 0  # Reset error counter - skip is not an error
                    else:
                        # File was successfully processed
                        # Mark file as tagged (this sets needs_tagging=0, tagged=1)
                        db.library_files.mark_file_tagged(file_id, config.tagger_version)

                        # Release claim AFTER marking tagged
                        release_claim(db, file_id)

                        files_processed += 1
                        consecutive_errors = 0

                        logger.info(
                            "[%s] Completed %s in %.2fs (%d heads, %d tags)",
                            self.worker_id,
                            result.file_path,
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
                        logger.exception(
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
                with contextlib.suppress(Exception):
                    self._health_pipe.close()

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
    execution_tier: int = 0,
    prefer_gpu: bool = True,
) -> DiscoveryWorker:
    """Factory function to create a DiscoveryWorker.

    Args:
        worker_index: Worker index (0, 1, 2, ...)
        db_hosts: ArangoDB host URL(s)
        db_password: Database password
        processor_config: ProcessorConfig for the processing workflow
        stop_event: Optional shared Event for coordinated shutdown
        health_pipe: Pipe write-end for health telemetry to parent
        execution_tier: Execution tier (0-4) from admission control
        prefer_gpu: Whether to prefer GPU for backbone execution

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
        execution_tier=execution_tier,
        prefer_gpu=prefer_gpu,
    )
