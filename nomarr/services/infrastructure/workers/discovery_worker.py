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
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from multiprocessing import Event
from typing import TYPE_CHECKING, Any

from nomarr.helpers.time_helper import internal_s

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event as EventType

    from nomarr.components.ml.onnx.ml_cache import ONNXModelCache
    from nomarr.helpers.dto.processing_dto import DeferredFileWrites, ProcessorConfig
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Worker configuration
HEALTH_FRAME_INTERVAL_S = 3.0  # Send health frame every 3 seconds (faster than 5s staleness check)
IDLE_SLEEP_S = 1.0  # Sleep when no work available
MAX_CONSECUTIVE_ERRORS = 10  # Shutdown after this many consecutive failures
CACHE_IDLE_TIMEOUT_S = 40  # Evict cache after 40 seconds of no work (matches default)
IDLE_POLLS_BEFORE_PROMOTION: int = 3  # Trigger hot→cold promotion after this many idle polls

# Health frame prefix
HEALTH_FRAME_PREFIX = "HEALTH|"


def _malloc_trim() -> None:
    """Advise glibc to release free heap pages back to the OS.

    Called after large per-track numpy arrays are freed (post-workflow) and
    after the ONNX cache is evicted at idle.  This prevents glibc arena pools
    from retaining freed pages across the 29K-track high-water mark.

    No-op on non-Linux platforms or if libc.so.6 is unavailable.
    """
    import ctypes
    import sys

    if sys.platform != "linux":
        return
    with contextlib.suppress(OSError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _execute_deferred_writes(
    db: Database,
    writes: DeferredFileWrites,
    worker_id: str,
) -> None:
    """Execute deferred DB writes for one file on a background thread.

    Order: save_tags → tag_model_output edges → set_chromaprint
           → compute_segment_stats → upsert_stats → mark_tagged
           → release_claim.
    Segment stats are computed here (deferred from the ML hot path) so the
    pipeline doesn't pay numpy reduction costs per head during inference.
    mark_tagged only runs if prior writes succeeded. release_claim always runs.
    """
    from nomarr.components.library.file_sync_comp import save_file_tags, set_chromaprint
    from nomarr.components.ml.inference.ml_segment_stats_comp import compute_segment_stats
    from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
    from nomarr.components.workers.worker_discovery_comp import release_claim

    file_id = writes.file_id
    try:
        # 1. Parse and write ML prediction tags with nom: prefix
        parsed_nom_tags = parse_tag_values(writes.db_tags) if writes.db_tags else {}
        prefixed_nom_tags = {
            (f"nom:{rel}" if not rel.startswith("nom:") else rel): values
            for rel, values in parsed_nom_tags.items()
        }
        save_file_tags(db, file_id, prefixed_nom_tags)

        # 2. Write tag_model_output edges (link tags to ML model outputs)
        if writes.ml_edges:
            output_edges = writes.ml_edges.output_edges
            pairs = [(rel, score) for rel, (_, score) in output_edges.items()]
            tag_ids = db.tags.resolve_tag_ids(pairs)
            edge_tuples: list[tuple[str, str, float]] = []
            for tag_rel, (output_id, score) in output_edges.items():
                tag_id = tag_ids.get((tag_rel, score))
                if tag_id is not None:
                    edge_tuples.append((tag_id, output_id, score))
            if edge_tuples:
                db.tag_model_output.write_edges_batch(edge_tuples)

        # 3. Store chromaprint fingerprint
        if writes.chromaprint:
            set_chromaprint(db, file_id, writes.chromaprint)

        # 4. Compute segment statistics from raw scores (deferred from hot path)
        if writes.raw_segments:
            stats_entries: list[dict[str, Any]] = []
            for head_name, (segment_scores, labels) in writes.raw_segments.items():
                label_stats = compute_segment_stats(segment_scores, labels)
                stats_entries.append({
                    "file_id": file_id,
                    "head_name": head_name,
                    "tagger_version": writes.tagger_version,
                    "num_segments": segment_scores.shape[0],
                    "pooling_strategy": "trimmed_mean",
                    "label_stats": label_stats,
                })
            if stats_entries:
                db.segment_scores_stats.upsert_stats_batch(stats_entries)

        # 5. All writes succeeded — mark file as tagged
        db.library_files.mark_file_tagged(file_id, writes.tagger_version)
        logger.debug("[%s] Async writes done for %s (%d tags)", worker_id, writes.path, len(writes.db_tags))
    except Exception:
        logger.exception("[%s] Async write failed for %s — file will be retried", worker_id, writes.path)
    finally:
        # 6. Always release claim so file is re-discoverable on failure
        release_claim(db, file_id)
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

        # Enable faulthandler for native crash tracebacks (SIGSEGV, SIGFPE, etc.)
        import faulthandler

        faulthandler.enable()

        import setproctitle

        setproctitle.setproctitle(f"nomarr-{self.worker_id}")

        # Register stop event for shutdown-aware audio loading
        from nomarr.components.ml.audio.ml_audio_comp import set_stop_event

        set_stop_event(self._stop_event)

        # Late imports to avoid import-time issues in subprocess
        from nomarr.components.ml.onnx.ml_session_comp import is_available as ml_is_available
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
            logger.error("[%s] ML backend (ONNX) not available - marking unhealthy", self.worker_id)
            self._current_status = "unhealthy"
            # Keep emitting unhealthy status for a short time, then exit
            time.sleep(10)
            return

        # Create database connection in subprocess
        db = Database(hosts=self.db_hosts, password=self.db_password)

        # Register worker context for process-local ML coordinator access
        from nomarr.components.ml.resources.ml_worker_context_comp import register_worker_context
        register_worker_context(db, self.worker_id)

        # Clear any stale VRAM promises from a previous crash of this worker.
        # The service owner also does this via on_status_change("dead"), but we
        # clear here too in case of a restart race or service-side failure.
        from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
        try:
            release_worker_promises(db, self.worker_id)
        except Exception:
            logger.debug("[%s] Failed to clear stale VRAM promises at startup", self.worker_id, exc_info=True)

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
            "[%s] Discovery worker started (pid=%s, tier=%d, prefer_gpu=%s)",
            self.worker_id,
            os.getpid(),
            self.execution_tier,
            self.prefer_gpu,
        )

        consecutive_errors = 0
        files_processed = 0
        cache_warmed = False  # Lazy cache warmup - only warm when work arrives
        last_work_time: float | None = None  # Monotonic timestamp of last successful file claim
        onnx_cache: ONNXModelCache | None = None  # ONNX model cache, lazily warmed
        recovering_until: float | None = None  # Recovery deadline if in recovering state
        idle_consecutive_polls: int = 0  # Count of consecutive idle polls (for promotion trigger)
        promotion_running: threading.Thread | None = None  # Background promotion thread
        promotion_suppressed: bool = False  # True when last promotion found nothing to do

        # Single-thread executor for async DB writes — overlaps I/O with next file's ML
        write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-write")
        pending_write: Future[None] | None = None

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
                file_id = discover_and_claim_file(
                    db,
                    self.worker_id,
                    min_duration_s=config.min_duration_s,
                    allow_short=config.allow_short,
                )

                if file_id is None:
                    idle_consecutive_polls += 1
                    logger.debug("[%s] No work found, sleeping %.1fs", self.worker_id, IDLE_SLEEP_S)
                    # Evict ONNX cache after idle timeout
                    if (
                        onnx_cache is not None
                        and last_work_time is not None
                        and internal_s().value - last_work_time > CACHE_IDLE_TIMEOUT_S
                    ):
                        onnx_cache.warm = False
                        onnx_cache = None
                        cache_warmed = False
                        logger.info("[%s] ONNX cache evicted due to idle timeout", self.worker_id)
                        # Belt-and-suspenders: reclaim any remaining fragmented pages that
                        # survived the per-track trim (e.g. ORT's internal session buffers
                        # which are only freed when the cache is evicted, not per-track).
                        _malloc_trim()

                    # Spawn idle vector promotion if enough consecutive idle polls
                    # and a previous run didn't already report "nothing to promote".
                    # promotion_suppressed resets when new work arrives (new hot vectors).
                    if (
                        idle_consecutive_polls >= IDLE_POLLS_BEFORE_PROMOTION
                        and not promotion_suppressed
                        and (promotion_running is None or not promotion_running.is_alive())
                    ):
                        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
                            idle_promotion_vectors_workflow as run_idle_promotion,
                        )

                        def _promotion_wrapper(
                            _db: Database,
                            _wid: str,
                            _mdir: str,
                        ) -> None:
                            nonlocal promotion_suppressed
                            promoted = run_idle_promotion(_db, _wid, _mdir)
                            if promoted == 0:
                                promotion_suppressed = True

                        promotion_running = threading.Thread(
                            target=_promotion_wrapper,
                            args=(db, self.worker_id, config.models_dir),
                            daemon=True,
                            name=f"VecPromo-{self.worker_id}",
                        )
                        promotion_running.start()
                        idle_consecutive_polls = 0
                        logger.info("[%s] Spawning idle vector promotion thread", self.worker_id)

                    time.sleep(IDLE_SLEEP_S)
                    continue

                logger.debug("[%s] Work found: claimed file %s", self.worker_id, file_id)
                idle_consecutive_polls = 0
                promotion_suppressed = False  # New work may produce hot vectors to promote
                last_work_time = internal_s().value

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

                # Lazy cache warmup: warm ONNX model cache on first file discovered
                # This avoids VRAM allocation until actual work arrives
                if not cache_warmed:
                    logger.debug("[%s] Warming ONNX model cache...", self.worker_id)
                    try:
                        from nomarr.components.ml.onnx.ml_base import DevicePlacement as _DevicePlacement
                        from nomarr.components.ml.onnx.ml_cache import (
                            ONNXModelCache as _ONNXModelCache,
                        )
                        from nomarr.components.ml.resources.ml_vram_probe_comp import (
                            has_model_vram_measurements,
                            probe_all_models,
                        )
                        from nomarr.components.platform.resource_monitor_comp import (
                            check_nvidia_gpu_capability,
                        )
                        if (
                            self.prefer_gpu
                            and check_nvidia_gpu_capability()
                            and not has_model_vram_measurements(db)
                        ):
                            logger.info("[%s] Running per-model VRAM probe...", self.worker_id)
                            probe_all_models(db, config.models_dir)
                        _cache_device: _DevicePlacement = "gpu" if self.prefer_gpu else "cpu"
                        onnx_cache = _ONNXModelCache(config.models_dir, _cache_device, db=db)
                        from nomarr.components.ml.resources import ml_vram_coordinator_comp as _coordinator
                        onnx_cache.warm = True
                        _fleet = _coordinator.get_fleet_vram_state(db)
                        _vram = _fleet["vram"]
                        _promises = _fleet["promises"]
                        _device_lookup: dict[str, str] = {
                            m._path: (m._device or "cpu").upper()
                            for m in onnx_cache._all_models()
                        }
                        _promise_rows = [
                            f"  {p.get('worker_id', '?'):<20}  "
                            f"{os.path.basename(p.get('model_path', '?')):<40}  "
                            f"{p.get('promised_mb', 0):.0f} MB"
                            f"  [{_device_lookup.get(p.get('model_path', ''), 'UNKNOWN')}]"
                            for p in _promises
                        ]
                        logger.info(
                            "[%s] ONNX cache ready (%d models). "
                            "Fleet promises: %d  |  GPU %d/%d MB\n%s",
                            self.worker_id,
                            onnx_cache.model_count,
                            len(_promises),
                            _vram.get("used_mb", 0),
                            _vram.get("total_mb", 0),
                            "\n".join(_promise_rows) if _promise_rows else "  (none)",
                        )
                    except Exception as e:
                        logger.exception("[%s] Failed to warm ONNX model cache: %s", self.worker_id, e)
                        # Continue anyway - workflow will create sessions inline (slower but works)
                    cache_warmed = True

                # Process the claimed file
                try:
                    # Get file path from database
                    logger.debug("[%s] Fetching file doc for %s", self.worker_id, file_id)
                    file_doc = db.library_files.get_file_by_id(file_id)
                    if not file_doc:
                        logger.warning("[%s] Claimed file %s not found in database", self.worker_id, file_id)
                        release_claim(db, file_id)
                        continue

                    file_path = file_doc["path"]

                    # Pre-call diagnostics with file size (native crash logging)
                    import sys

                    try:
                        file_size = os.path.getsize(file_path)
                    except OSError:
                        file_size = -1
                    logger.debug(
                        "[%s] Processing %s (size=%d bytes)", self.worker_id, file_path, file_size
                    )
                    sys.stdout.flush()
                    sys.stderr.flush()

                    # Run the processing workflow
                    assert onnx_cache is not None, "onnx_cache must be warmed before processing"
                    result = process_file_workflow(
                        path=file_path,
                        config=config,
                        db=db,
                        file_id=file_id,
                        cache=onnx_cache,
                    )
                    logger.debug("[%s] Workflow returned for %s", self.worker_id, file_path)
                    # Large per-track allocations (audio waveform, mel spectrogram, backbone
                    # embeddings) are freed when process_file_workflow returns.  Trim the
                    # glibc heap now so those pages return to the OS rather than sitting in
                    # arena pools until the end of the library run.
                    _malloc_trim()

                    # Wait for previous file's async writes to finish (backpressure)
                    if pending_write is not None:
                        pending_write.result()  # raises if write thread had unhandled error
                        pending_write = None

                    # Check if file was skipped (e.g., audio too short)
                    if result.heads_processed == 0 and result.tags_written == 0:
                        # File was skipped — mark tagged synchronously (no data to write)
                        logger.info(
                            "[%s] Skipped %s (all heads skipped - likely too short)",
                            self.worker_id,
                            file_path,
                        )
                        db.library_files.mark_file_tagged(file_id, config.tagger_version)
                        release_claim(db, file_id)
                        files_processed += 1
                        consecutive_errors = 0
                    elif result.deferred_writes is not None:
                        # File processed — submit writes to background thread
                        pending_write = write_executor.submit(
                            _execute_deferred_writes, db, result.deferred_writes, self.worker_id,
                        )
                        files_processed += 1
                        consecutive_errors = 0

                        timing = f" | {result.timing_summary}" if result.timing_summary else ""
                        logger.info(
                            "[%s] Completed %s in %.2fs (%d heads, %d tags)%s",
                            self.worker_id,
                            result.file_path,
                            result.elapsed,
                            result.heads_processed,
                            result.tags_written,
                            timing,
                        )
                    else:
                        # No deferred writes (no db) — just release
                        release_claim(db, file_id)
                        files_processed += 1
                        consecutive_errors = 0

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
            # Drain any pending async writes before shutdown
            if pending_write is not None:
                try:
                    pending_write.result(timeout=30)
                except Exception:
                    logger.exception("[%s] Pending write failed during shutdown", self.worker_id)
            write_executor.shutdown(wait=True)

            # Wait for in-progress promotion to finish gracefully
            if promotion_running is not None and promotion_running.is_alive():
                promotion_running.join(timeout=60)

            # Cleanup on exit
            logger.info(
                "[%s] Discovery worker stopping (processed %d files)",
                self.worker_id,
                files_processed,
            )
            db.health.mark_stopping(self.worker_id)

            # Release VRAM promises — belt-and-suspenders for graceful exits;
            # the service owner handles this for crashes via on_status_change("dead")
            try:
                from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
                release_worker_promises(db, self.worker_id)
            except Exception:
                logger.debug("[%s] Failed to release VRAM promises on shutdown", self.worker_id, exc_info=True)

            # Shut down persistent audio loader subprocess
            from nomarr.components.ml.audio.ml_audio_comp import shutdown_audio_loader

            shutdown_audio_loader()

            # Shut down head prediction thread pool (bounded exit)
            from nomarr.components.ml.inference.ml_head_pipeline_comp import shutdown_head_pool

            shutdown_head_pool()

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
