"""CalibrationService - Thin orchestration wrapper for calibration generation workflow.

This service delegates to workflows.calibration_generation for the actual calibration logic.
It provides dependency injection (db, models_dir, namespace, thresholds) from the application
context to the pure workflow function.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict
from typing import cast as type_cast

from nomarr.components.ml.calibration.ml_calibration_state_comp import compute_reconciliation_info
from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db
from nomarr.helpers import ManagedTask
from nomarr.helpers.time_helper import now_ms
from nomarr.workflows.calibration.generate_calibration_wf import (
    generate_histogram_calibration_wf,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService


logger = logging.getLogger(__name__)

CALIBRATION_GENERATE_TASK_ID = "calibration_generate"


class HistogramGenerationStatusDict(TypedDict):
    """Background histogram-generation lifecycle snapshot."""

    running: bool
    completed: bool
    error: str | None
    result: dict[str, Any] | None


class HistogramGenerationProgressDict(TypedDict):
    """Background histogram-generation per-head progress snapshot."""

    current_head: str | None
    current_head_index: int | None
    total_heads: int
    completed_heads: int
    remaining_heads: int
    last_updated: int | None
    is_running: bool


class HistogramGenerationCombinedStatusDict(TypedDict):
    """Combined background histogram-generation lifecycle and progress snapshot."""

    running: bool
    completed: bool
    error: str | None
    result: dict[str, Any] | None
    current_head: str | None
    current_head_index: int | None
    total_heads: int
    completed_heads: int
    remaining_heads: int
    last_updated: int | None
    is_running: bool


@dataclass
class CalibrationConfig:
    """Configuration for CalibrationService."""

    models_dir: str
    namespace: str
    thresholds: dict[str, float] = field(default_factory=dict)


class CalibrationService:
    """Service for orchestrating calibration generation.

    Thin wrapper that provides DI to the calibration workflow.
    All domain logic lives in workflows.calibration_generation.
    """

    def __init__(
        self,
        db: Database,
        cfg: CalibrationConfig,
        bts: BackgroundTaskService,
    ) -> None:
        """Initialize calibration service.

        Args:
            db: Database instance
            cfg: Calibration configuration
            bts: BackgroundTaskService for managed background task execution

        """
        self._db = db
        self.cfg = cfg
        self._bts = bts
        self._generation_result: dict[str, Any] | None = None
        self._generation_error: Exception | None = None
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {}
        self._post_generation_hook: Callable[[], None] | None = None

    def set_post_generation_hook(self, hook: Callable[[], None]) -> None:
        """Register a callable to be invoked after successful histogram generation.

        The hook is called only when generation completes with heads_failed == 0.
        Intended for wiring at the composition root (app.py) — not configuration.

        Args:
            hook: Zero-argument callable, e.g. tagging_service.start_apply_calibration_background

        """

        def guarded_hook() -> None:
            result = self._generation_result
            if result is None:
                logger.warning("[CalibrationService] Post-generation hook skipped: no generation result available")
                return
            if result.get("heads_failed") != 0:
                logger.info(
                    "[CalibrationService] Generation complete with %s failed head(s); skipping auto-apply",
                    result.get("heads_failed"),
                )
                return

            logger.info("[CalibrationService] Generation complete — auto-triggering calibration apply")
            hook()

        self._post_generation_hook = guarded_hook

    # -------------------------------------------------------------------------
    #  Histogram-Based Calibration (Primary System)
    # -------------------------------------------------------------------------

    def generate_histogram_calibration(self) -> dict[str, Any]:
        """Generate calibrations using sparse uniform histogram approach.

        Stateless, idempotent. Always computes from current DB state.
        Uses 10,000 uniform bins per head, sparse results only.

        Returns:
            {
              "version": int,
              "heads_processed": int,
              "heads_success": int,
              "heads_failed": int,
              "results": {head_key: {p5, p95, n, underflow_count, overflow_count}},
              "global_version": str,
              "requires_reconciliation": bool,
              "affected_libraries": [{library_id, name, outdated_files}]
            }

        """
        logger.debug("[CalibrationService] Delegating to histogram calibration workflow")

        result = generate_histogram_calibration_wf(
            db=self._db,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            progress_callback=self._update_progress,
        )

        # Compute reconciliation info after calibration completes
        reconciliation_info = compute_reconciliation_info(
            self._db,
            result.get("global_version"),
        )
        result["requires_reconciliation"] = reconciliation_info["requires_reconciliation"]
        result["affected_libraries"] = reconciliation_info["affected_libraries"]

        return result

    def start_histogram_calibration_background(self) -> None:
        """Start histogram-based calibration generation in a managed background task.

        Dispatches via BackgroundTaskService using a ManagedTask.
        Thread-safe: can check is_generation_running() and get_generation_result().
        """
        if self.is_generation_running():
            logger.warning("[CalibrationService] Calibration generation already running")
            return

        # Reset state
        self._generation_result = None
        self._generation_error = None
        self._clear_progress()

        task = ManagedTask(
            task_id=CALIBRATION_GENERATE_TASK_ID,
            fn=self._run_histogram_generation,
            on_complete=self._post_generation_hook,
            daemon=False,
        )
        try:
            self._bts.start_task(task)
        except ValueError:
            logger.warning("[CalibrationService] Calibration generation already running")
            return

        logger.info("[CalibrationService] Started histogram calibration generation in background")

    # -- Threading infrastructure (NOT domain logic; see services.instructions.md) --

    def _update_progress(self, **kwargs: int | str | None) -> None:
        """Thread-safe update of progress state from background thread.

        Args:
            **kwargs: Progress fields to update. Valid keys:
                current_head, current_head_index, total_heads

        """
        with self._progress_lock:
            self._progress.update(kwargs)

    def _clear_progress(self) -> None:
        """Reset progress state (called when generation starts or finishes)."""
        with self._progress_lock:
            self._progress = {}

    def _run_histogram_generation(self) -> dict[str, Any]:
        """Managed background task: run histogram calibration generation."""
        try:
            logger.info("[CalibrationService] Background generation started")
            result = self.generate_histogram_calibration()
            self._generation_result = result
            logger.info(
                f"[CalibrationService] Background generation completed: "
                f"{result['heads_success']} success, {result['heads_failed']} failed",
            )
            return result
        except Exception as e:
            logger.error(f"[CalibrationService] Background generation failed: {e}", exc_info=True)
            self._generation_error = e
            raise
        finally:
            self._clear_progress()

    def is_generation_running(self) -> bool:
        """Check if histogram calibration generation is currently running."""
        status = self._bts.get_task_status(CALIBRATION_GENERATE_TASK_ID)
        return status is not None and status.get("status") == "running"

    def get_generation_result(self) -> dict[str, Any] | None:
        """Get result of last histogram calibration generation.

        Returns:
            Result dict if generation completed successfully, None if still running or failed

        """
        return self._generation_result

    def get_generation_error(self) -> Exception | None:
        """Get error from last histogram calibration generation.

        Returns:
            Exception if generation failed, None if still running or succeeded

        """
        return self._generation_error

    def _get_generation_status(self) -> HistogramGenerationStatusDict:
        """Get current status of histogram calibration generation.

        Returns:
            {
              "running": bool,
              "completed": bool,
              "error": str | None,
              "result": dict | None
            }

        """
        running = self.is_generation_running()
        completed = self._generation_result is not None
        error = str(self._generation_error) if self._generation_error else None

        return {
            "running": running,
            "completed": completed,
            "error": error,
            "result": self._generation_result,
        }

    def _get_generation_progress(self) -> HistogramGenerationProgressDict:
        """Get calibration generation progress.

        When generation is running, returns live progress from background thread:
            current_head, current_head_index, total_heads

        When not running, falls back to DB query for head completion counts.

        Returns:
            {
              "total_heads": int,
              "completed_heads": int,
              "remaining_heads": int,
              "last_updated": int | None,
              "is_running": bool,
              "current_head": str | None,
              "current_head_index": int | None,
            }

        """
        is_running = self.is_generation_running()

        if is_running:
            # Return live progress from background thread
            with self._progress_lock:
                progress = dict(self._progress)
            return {
                "current_head": type_cast("str | None", progress.get("current_head")),
                "current_head_index": type_cast("int | None", progress.get("current_head_index")),
                "total_heads": progress.get("total_heads", 0),
                "completed_heads": 0,  # Not meaningful during generation
                "remaining_heads": 0,
                "last_updated": None,
                "is_running": True,
            }

        # Not running: fall back to DB query for head completion counts
        heads = discover_heads_no_db(self.cfg.models_dir)
        total_heads = len(heads)

        # Count heads with recent calibration_state (within 24 hours)
        recent_threshold = now_ms().value - (24 * 60 * 60 * 1000)
        completed = self._db.calibration_state.count_recent(recent_threshold)

        # Get most recent calibration timestamp
        last_updated = self._db.calibration_state.get_latest_updated_at()

        return {
            "current_head": None,
            "current_head_index": None,
            "total_heads": total_heads,
            "completed_heads": completed,
            "remaining_heads": total_heads - completed,
            "last_updated": last_updated,
            "is_running": False,
        }

    def get_generation_combined_status(self) -> HistogramGenerationCombinedStatusDict:
        """Get combined lifecycle status and per-head progress for histogram generation.

        Returns:
            {
              "running": bool,
              "completed": bool,
              "error": str | None,
              "result": dict | None,
              "current_head": str | None,
              "current_head_index": int | None,
              "total_heads": int,
              "completed_heads": int,
              "remaining_heads": int,
              "last_updated": int | None,
              "is_running": bool,
            }

        """
        return {
            **self._get_generation_status(),
            **self._get_generation_progress(),
        }

    def get_histogram_for_head(self, model_key: str, head_name: str, label: str) -> dict[str, Any]:
        """Get stored histogram bins for a specific label.

        Args:
            model_key: Model identifier (e.g., "effnet-20220825")
            head_name: Head name (e.g., "mood_happy")
            label: Label name (e.g., "happy", "male")

        Returns:
            {
              "model_key": str,
              "head_name": str,
              "label": str,
              "histogram_bins": [{val: float, count: int}, ...],
              "p5": float,
              "p95": float,
              "n": int,
              "histogram_spec": {lo, hi, bins, bin_width}
            }

        Raises:
            ValueError: If no calibration state found for label

        """
        state = self._db.calibration_state.get_calibration_state(head_name, label)
        if not state:
            raise ValueError(f"No calibration state found for {model_key}:{head_name}:{label}")

        return {
            "model_key": model_key,
            "head_name": head_name,
            "label": label,
            "histogram_bins": state.get("histogram_bins", []),
            "p5": state.get("p5"),
            "p95": state.get("p95"),
            "n": state.get("n"),
            "histogram_spec": state.get("histogram", {}),
        }

    def get_all_calibration_states(self) -> list[dict[str, Any]]:
        """Get all calibration states with histogram bins.

        Returns:
            List of calibration state documents with histogram_bins

        """
        return self._db.calibration_state.get_all_calibration_states()

    # -------------------------------------------------------------------------

    def clear_calibration(self) -> dict[str, int]:
        """Clear all calibration data from the database.

        Removes calibration_state, calibration_history, meta keys,
        and nulls calibration_hash on all library files.

        Returns:
            Summary: {files_updated, meta_keys_cleared}

        Raises:
            RuntimeError: If calibration generation is currently running.

        """
        if self.is_generation_running():
            msg = "Cannot clear calibration while generation is running."
            raise RuntimeError(msg)

        from nomarr.components.ml.calibration.ml_calibration_state_comp import clear_all_calibration_data

        return clear_all_calibration_data(self._db)

    # -------------------------------------------------------------------------
    #  Reconciliation Info
