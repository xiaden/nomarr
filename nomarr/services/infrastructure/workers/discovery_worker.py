"""Discovery worker subprocess for ML-based file tagging."""

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

from nomarr.components.library.library_file_mutation_comp import update_last_tagged_at
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_TAGGED,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.helpers.time_helper import internal_s, now_ms

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event as EventType

    from nomarr.components.ml.onnx.ml_cache import ONNXModelCache
    from nomarr.helpers.dto.processing_dto import DeferredFileWrites, ProcessorConfig, ResourceManagementConfig
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)
HEALTH_FRAME_INTERVAL_S = 3.0  # Send health frame every 3 seconds (faster than 5s staleness check)
IDLE_SLEEP_S = 1.0  # Sleep when no work available
MAX_CONSECUTIVE_ERRORS = 10  # Shutdown after this many consecutive failures
CACHE_IDLE_TIMEOUT_S = 40  # Evict cache after 40 seconds of no work (matches default)
IDLE_POLLS_BEFORE_PROMOTION: int = 3  # Trigger hot→cold promotion after this many idle polls
HEALTH_FRAME_PREFIX = "HEALTH|"


def _check_idle_pipeline_completion(db: Database, health_pipe: Any) -> int:
    """Transition idle ML-complete libraries and signal calibration health updates."""
    from nomarr.components.library.library_records_comp import find_ml_complete_libraries
    from nomarr.components.library.scan_lifecycle_comp import transition_pipeline_state
    from nomarr.helpers.constants.pipeline_states import PIPELINE_AWAITING_CALIBRATION, PIPELINE_TOO_SMALL
    from nomarr.helpers.dto.health_dto import PIPELINE_FRAME_PREFIX
    from nomarr.services.infrastructure.config_svc import INTERNAL_CALIBRATION_MIN_FILES

    completed = find_ml_complete_libraries(db, INTERNAL_CALIBRATION_MIN_FILES)
    transitions_fired = 0
    for result in completed:
        library_id = result["library_id"]
        tagged_count = result["tagged_count"]
        target_state = (
            PIPELINE_AWAITING_CALIBRATION if tagged_count >= INTERNAL_CALIBRATION_MIN_FILES else PIPELINE_TOO_SMALL
        )
        transition_pipeline_state(db, library_id, target_state)
        transitions_fired += 1
    if transitions_fired > 0 and health_pipe is not None:
        try:
            health_pipe.send(PIPELINE_FRAME_PREFIX + "calibration_trigger")
        except (OSError, BrokenPipeError) as exc:
            logger.debug("Idle pipeline trigger send failed: %s", exc)
    return transitions_fired


def _malloc_trim() -> None:
    """Release freed heap memory back to the OS on Linux."""
    import ctypes
    import sys

    if sys.platform != "linux":
        return
    with contextlib.suppress(OSError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _execute_deferred_writes(db: Database, writes: DeferredFileWrites, worker_id: str) -> None:
    """Persist deferred file writes and release the worker claim."""
    from nomarr.components.library.file_sync_comp import save_file_tags
    from nomarr.components.library.library_file_mutation_comp import set_chromaprint
    from nomarr.components.library.library_file_state_comp import transition_file_state
    from nomarr.components.ml.inference.ml_output_stream_store_comp import StreamWrite, upsert_output_streams
    from nomarr.components.ml.onnx.tag_model_output_comp import write_tag_model_output_edges_batch
    from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
    from nomarr.components.tagging.tag_write_comp import resolve_tag_ids
    from nomarr.components.workers.worker_discovery_comp import release_claim

    file_id = writes.file_id
    try:
        parsed_nom_tags = parse_tag_values(writes.db_tags) if writes.db_tags else {}
        prefixed_nom_tags = {
            (f"nom:{name}" if not name.startswith("nom:") else name): values for name, values in parsed_nom_tags.items()
        }
        save_file_tags(db, file_id, prefixed_nom_tags)
        if writes.ml_edges:
            output_edges = writes.ml_edges.output_edges
            pairs = [(name, score) for name, (_, score) in output_edges.items()]
            tag_ids = resolve_tag_ids(db, pairs)
            edge_tuples: list[tuple[str, str, float]] = []
            for tag_name, (output_id, score) in output_edges.items():
                tag_id = tag_ids.get((tag_name, score))
                if tag_id is not None:
                    edge_tuples.append((tag_id, output_id, score))
            if edge_tuples:
                write_tag_model_output_edges_batch(db, edge_tuples)
        if writes.chromaprint:
            set_chromaprint(db, file_id, writes.chromaprint)
        if writes.raw_output_streams:
            upsert_output_streams(
                db,
                file_id=file_id,
                streams=[
                    StreamWrite(output_id=stream.output_id, values=stream.values)
                    for stream in writes.raw_output_streams
                ],
            )
        transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
        update_last_tagged_at(db, file_id)
        transition_file_state(db, [file_id], STATE_NOT_VECTORS_EXTRACTED, STATE_VECTORS_EXTRACTED)
        logger.debug("[%s] Async writes done for %s (%d tags)", worker_id, writes.path, len(writes.db_tags))
    except Exception:
        try:
            transition_file_state(db, [file_id], STATE_NOT_ERRORED, STATE_ERRORED)
        except Exception:
            logger.debug("[%s] Failed to set errored state for %s", worker_id, file_id, exc_info=True)
        logger.exception("[%s] Async write failed for %s — file will be retried", worker_id, writes.path)
    finally:
        release_claim(db, file_id)


class DiscoveryWorker(multiprocessing.Process):
    """Multiprocessing worker that claims and processes audio files through the ML pipeline."""

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
        """Initialize the discovery worker process."""
        super().__init__()
        self.worker_id = worker_id
        self.db_hosts = db_hosts
        self.db_password = db_password
        self.processor_config_dict = processor_config_dict
        self._stop_event = stop_event or Event()
        self._health_pipe = health_pipe
        self._current_status: str = "pending"
        self.execution_tier = execution_tier
        self.prefer_gpu = prefer_gpu

    def _configure_subprocess_logging(self) -> None:
        import logging.handlers
        import sys
        from pathlib import Path

        from nomarr.helpers.logging_helper import NomarrLogFilter

        log_format = "%(asctime)s %(levelname)s %(nomarr_identity_tag)s %(nomarr_role_tag)s%(context_str)s%(message)s"
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "nomarr.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(log_format))
        file_handler.addFilter(NomarrLogFilter())
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(log_format))
        console_handler.addFilter(NomarrLogFilter())
        logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler], force=True)

    def _send_health_frame(self, status: str) -> None:
        if self._health_pipe is None:
            return
        frame = HEALTH_FRAME_PREFIX + json.dumps({"component_id": self.worker_id, "status": status})
        try:
            self._health_pipe.send(frame)
        except (OSError, BrokenPipeError) as exc:
            logger.debug("[%s] Failed to send health frame: %s", self.worker_id, exc)

    def _health_writer_loop(self) -> None:
        while not self._stop_event.is_set():
            self._send_health_frame(self._current_status)
            for _ in range(int(HEALTH_FRAME_INTERVAL_S * 10)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

    def _preflight_and_connect(self) -> tuple[Database, ProcessorConfig, ResourceManagementConfig | None] | None:
        """Run worker startup, connect to the database, and return initialized runtime state."""
        import faulthandler

        import setproctitle  # type: ignore[import-untyped]

        from nomarr.components.ml.audio.ml_audio_comp import set_stop_event
        from nomarr.components.ml.onnx.ml_session_comp import is_available as ml_is_available
        from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
        from nomarr.components.ml.resources.ml_worker_context_comp import register_worker_context
        from nomarr.helpers.dto.processing_dto import ProcessorConfig
        from nomarr.persistence.db import Database

        self._configure_subprocess_logging()
        faulthandler.enable()
        setproctitle.setproctitle(f"nomarr-{self.worker_id}")
        set_stop_event(self._stop_event)
        if self._health_pipe is not None:
            threading.Thread(
                target=self._health_writer_loop, daemon=True, name=f"HealthWriter-{self.worker_id}"
            ).start()
        if not ml_is_available():
            logger.error("[%s] ML backend (ONNX) not available - marking unhealthy", self.worker_id)
            self._current_status = "unhealthy"
            time.sleep(10)
            return None
        db = Database(hosts=self.db_hosts, password=self.db_password)
        register_worker_context(db, self.worker_id)
        try:
            release_worker_promises(db, self.worker_id)
        except Exception:
            logger.debug("[%s] Failed to clear stale VRAM promises at startup", self.worker_id, exc_info=True)
        config = ProcessorConfig(**self.processor_config_dict)
        self._current_status = "healthy"
        db.health.component_id.upsert(
            self.worker_id,
            {
                "component_type": "worker",
                "status": "starting",
                "last_heartbeat": now_ms().value,
            },
        )
        db.health.component_id.update(
            self.worker_id,
            {"status": "healthy", "error": None, "last_heartbeat": now_ms().value},
        )
        logger.info(
            "[%s] Discovery worker started (pid=%s, tier=%d, prefer_gpu=%s)",
            self.worker_id,
            os.getpid(),
            self.execution_tier,
            self.prefer_gpu,
        )
        return db, config, config.resource_management

    def _evict_idle_cache(
        self, onnx_cache: ONNXModelCache | None, last_work_time: float | None, cache_warmed: bool
    ) -> tuple[ONNXModelCache | None, bool]:
        if onnx_cache is None or last_work_time is None or internal_s().value - last_work_time <= CACHE_IDLE_TIMEOUT_S:
            return onnx_cache, cache_warmed
        onnx_cache.warm = False
        logger.info("[%s] ONNX cache evicted due to idle timeout", self.worker_id)
        _malloc_trim()
        return None, False

    def _maybe_spawn_idle_promotion(
        self,
        db: Database,
        models_dir: str,
        idle_consecutive_polls: int,
        promotion_running: threading.Thread | None,
        promotion_state: dict[str, bool],
    ) -> tuple[threading.Thread | None, int]:
        if (
            idle_consecutive_polls < IDLE_POLLS_BEFORE_PROMOTION
            or promotion_state["suppressed"]
            or self._stop_event.is_set()
            or (promotion_running is not None and promotion_running.is_alive())
        ):
            return promotion_running, idle_consecutive_polls
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow as run_idle_promotion,
        )

        def _promotion_wrapper() -> None:
            if run_idle_promotion(db, self.worker_id, models_dir) == 0:
                promotion_state["suppressed"] = True

        promotion_running = threading.Thread(target=_promotion_wrapper, daemon=True, name=f"VecPromo-{self.worker_id}")
        promotion_running.start()
        logger.info("[%s] Spawning idle vector promotion thread", self.worker_id)
        return promotion_running, 0

    def _warm_onnx_cache(self, db: Database, config: ProcessorConfig) -> ONNXModelCache | None:
        """Warm the ONNX cache and probe GPU VRAM measurements when needed."""
        from nomarr.components.ml.onnx.ml_base import DevicePlacement as _DevicePlacement
        from nomarr.components.ml.onnx.ml_cache import ONNXModelCache as _ONNXModelCache
        from nomarr.components.ml.resources.ml_vram_probe_comp import has_model_vram_measurements, probe_all_models
        from nomarr.components.platform.resource_monitor_comp import check_nvidia_gpu_capability

        try:
            if self.prefer_gpu and check_nvidia_gpu_capability() and not has_model_vram_measurements(db):
                logger.info("[%s] Running per-model VRAM probe...", self.worker_id)
                probe_all_models(db, config.models_dir)
            cache_device: _DevicePlacement = "gpu" if self.prefer_gpu else "cpu"
            onnx_cache = _ONNXModelCache(config.models_dir, cache_device, db=db)
            from nomarr.components.ml.resources import ml_vram_coordinator_comp as _coordinator

            onnx_cache.warm = True
            fleet = _coordinator.get_fleet_vram_state(db)
            vram = fleet["vram"]
            promises = fleet["promises"]
            device_lookup = {m._path: (m._device or "cpu").upper() for m in onnx_cache._all_models()}
            promise_rows = [
                f"  {p.get('worker_id', '?'):<20}  {os.path.basename(p.get('model_path', '?')):<40}  "
                f"{p.get('promised_mb', 0):.0f} MB  [{device_lookup.get(p.get('model_path', ''), 'UNKNOWN')}]"
                for p in promises
            ]
            logger.info(
                "[%s] ONNX cache ready (%d models). Fleet promises: %d  |  GPU %d/%d MB\n%s",
                self.worker_id,
                onnx_cache.model_count,
                len(promises),
                vram.get("used_mb", 0),
                vram.get("total_mb", 0),
                "\n".join(promise_rows) if promise_rows else "  (none)",
            )
            return onnx_cache
        except Exception as exc:
            logger.exception("[%s] Failed to warm ONNX model cache: %s", self.worker_id, exc)
            return None

    def _check_resource_headroom(
        self, db: Database, file_id: str, rm_config: ResourceManagementConfig | None
    ) -> float | None:
        if rm_config is None or not rm_config.enabled:
            return None
        from nomarr.components.platform.resource_monitor_comp import check_resource_headroom
        from nomarr.components.workers.worker_discovery_comp import release_claim

        resource_status = check_resource_headroom(
            vram_budget_mb=rm_config.vram_budget_mb,
            ram_budget_mb=rm_config.ram_budget_mb,
            vram_estimate_mb=8192,
            ram_estimate_mb=2048,
            ram_detection_mode=rm_config.ram_detection_mode,
        )
        if not resource_status.vram_ok and not resource_status.ram_ok:
            logger.warning(
                "[%s] Resources exhausted (VRAM=%dMB, RAM=%dMB) - entering recovery",
                self.worker_id,
                resource_status.vram_used_mb,
                resource_status.ram_used_mb,
            )
            release_claim(db, file_id)
            self._current_status = "recovering"
            return internal_s().value + 30.0
        if not resource_status.vram_ok and resource_status.ram_ok:
            logger.info(
                "[%s] VRAM pressure, spilling to CPU (RAM=%dMB available)", self.worker_id, resource_status.ram_used_mb
            )
        return None

    def _process_claimed_file(
        self,
        db: Database,
        file_id: str,
        config: ProcessorConfig,
        onnx_cache: ONNXModelCache | None,
        pending_write: Future[None] | None,
        write_executor: ThreadPoolExecutor,
    ) -> tuple[Future[None] | None, bool]:
        """Process a claimed file and schedule any deferred database writes."""
        import sys

        from nomarr.components.library.library_file_query_comp import get_file_by_id
        from nomarr.components.library.library_file_state_comp import transition_file_state
        from nomarr.components.workers.worker_discovery_comp import release_claim
        from nomarr.workflows.processing.process_file_wf import process_file_workflow

        logger.debug("[%s] Fetching file doc for %s", self.worker_id, file_id)
        file_doc = get_file_by_id(db, file_id)
        if not file_doc:
            logger.warning("[%s] Claimed file %s not found in database", self.worker_id, file_id)
            release_claim(db, file_id)
            return pending_write, False
        file_path = file_doc["path"]
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = -1
        logger.debug("[%s] Processing %s (size=%d bytes)", self.worker_id, file_path, file_size)
        sys.stdout.flush()
        sys.stderr.flush()
        assert onnx_cache is not None, "onnx_cache must be warmed before processing"
        result = process_file_workflow(path=file_path, config=config, db=db, file_id=file_id, cache=onnx_cache)
        logger.debug("[%s] Workflow returned for %s", self.worker_id, file_path)
        _malloc_trim()
        if pending_write is not None:
            pending_write.result()
            pending_write = None
        if result.heads_processed == 0 and result.tags_written == 0:
            logger.info("[%s] Skipped %s (all heads skipped - likely too short)", self.worker_id, file_path)
            transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
            update_last_tagged_at(db, file_id)
            release_claim(db, file_id)
            return None, True
        if result.deferred_writes is not None:
            pending_write = write_executor.submit(_execute_deferred_writes, db, result.deferred_writes, self.worker_id)
            timing = f" | {result.timing_summary}" if result.timing_summary else ""
            logger.debug(
                "[%s] Completed %s in %.2fs (%d heads, %d tags)%s",
                self.worker_id,
                result.file_path,
                result.elapsed,
                result.heads_processed,
                result.tags_written,
                timing,
            )
            return pending_write, True
        release_claim(db, file_id)
        return pending_write, True

    def _handle_process_error(self, db: Database, file_id: str, error: Exception, consecutive_errors: int) -> int:
        from nomarr.components.library.library_file_state_comp import transition_file_state
        from nomarr.components.workers.worker_discovery_comp import release_claim

        next_errors = consecutive_errors + 1
        logger.exception("[%s] Error processing %s: %s", self.worker_id, file_id, error)
        try:
            transition_file_state(db, [file_id], STATE_NOT_ERRORED, STATE_ERRORED)
        except Exception:
            logger.debug("[%s] Failed to set errored state for %s", self.worker_id, file_id, exc_info=True)
        release_claim(db, file_id)
        if next_errors >= MAX_CONSECUTIVE_ERRORS:
            logger.exception("[%s] Too many consecutive errors (%d), shutting down", self.worker_id, next_errors)
        return next_errors

    def run(self) -> None:
        """Run the worker preflight and claim-process loop until shutdown."""
        setup = self._preflight_and_connect()
        if setup is None:
            return
        from nomarr.components.workers.worker_discovery_comp import discover_and_claim_file

        db, config, rm_config = setup
        consecutive_errors, files_processed = 0, 0
        cache_warmed = False
        last_work_time: float | None = None
        onnx_cache: ONNXModelCache | None = None
        recovering_until: float | None = None
        idle_consecutive_polls = 0
        promotion_running: threading.Thread | None = None
        promotion_state = {"suppressed": False}
        write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-write")
        pending_write: Future[None] | None = None

        try:
            while not self._stop_event.is_set():
                if recovering_until is not None:
                    if internal_s().value < recovering_until:
                        time.sleep(1.0)
                        continue
                    recovering_until = None
                    self._current_status = "healthy"
                    logger.info("[%s] Recovery window expired, resuming work", self.worker_id)

                logger.debug("[%s] Polling for work...", self.worker_id)
                file_id = discover_and_claim_file(db, self.worker_id)
                if file_id is None:
                    idle_consecutive_polls += 1
                    logger.debug("[%s] No work found, sleeping %.1fs", self.worker_id, IDLE_SLEEP_S)
                    onnx_cache, cache_warmed = self._evict_idle_cache(onnx_cache, last_work_time, cache_warmed)
                    promotion_running, idle_consecutive_polls = self._maybe_spawn_idle_promotion(
                        db, config.models_dir, idle_consecutive_polls, promotion_running, promotion_state
                    )
                    try:
                        _check_idle_pipeline_completion(db, self._health_pipe)
                    except Exception:
                        logger.debug("[%s] _check_idle_pipeline_completion failed", self.worker_id, exc_info=True)
                    time.sleep(IDLE_SLEEP_S)
                    continue

                logger.debug("[%s] Work found: claimed file %s", self.worker_id, file_id)
                idle_consecutive_polls = 0
                promotion_state["suppressed"] = False
                last_work_time = internal_s().value
                recovering_until = self._check_resource_headroom(db, file_id, rm_config)
                if recovering_until is not None:
                    continue
                if not cache_warmed:
                    logger.debug("[%s] Warming ONNX model cache...", self.worker_id)
                    onnx_cache = self._warm_onnx_cache(db, config)
                    cache_warmed = True

                try:
                    pending_write, processed = self._process_claimed_file(
                        db, file_id, config, onnx_cache, pending_write, write_executor
                    )
                    if processed:
                        files_processed += 1
                        consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors = self._handle_process_error(db, file_id, exc, consecutive_errors)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        break
        finally:
            if pending_write is not None:
                try:
                    pending_write.result(timeout=30)
                except Exception:
                    logger.exception("[%s] Pending write failed during shutdown", self.worker_id)
            write_executor.shutdown(wait=True)
            if promotion_running is not None and promotion_running.is_alive():
                promotion_running.join(timeout=8)
            logger.info("[%s] Discovery worker stopping (processed %d files)", self.worker_id, files_processed)
            db.health.component_id.update(self.worker_id, {"status": "stopping"})
            try:
                from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises

                release_worker_promises(db, self.worker_id)
            except Exception:
                logger.debug("[%s] Failed to release VRAM promises on shutdown", self.worker_id, exc_info=True)
            from nomarr.components.ml.audio.ml_audio_comp import shutdown_audio_loader
            from nomarr.components.ml.inference.ml_head_pipeline_comp import shutdown_head_pool

            shutdown_audio_loader()
            shutdown_head_pool()
            if self._health_pipe is not None:
                with contextlib.suppress(Exception):
                    self._health_pipe.close()

    def stop(self) -> None:
        """Signal the worker to stop."""
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
    """Create a discovery worker for the given index."""
    worker_id = f"worker:tag:{worker_index}"
    from dataclasses import asdict

    return DiscoveryWorker(
        worker_id=worker_id,
        db_hosts=db_hosts,
        db_password=db_password,
        processor_config_dict=asdict(processor_config),
        stop_event=stop_event,
        health_pipe=health_pipe,
        execution_tier=execution_tier,
        prefer_gpu=prefer_gpu,
    )
