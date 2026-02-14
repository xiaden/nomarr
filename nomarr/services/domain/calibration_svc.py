"""CalibrationService - Thin orchestration wrapper for calibration generation workflow.

This service delegates to workflows.calibration_generation for the actual calibration logic.
It provides dependency injection (db, models_dir, namespace, thresholds) from the application
context to the pure workflow function.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from typing import cast as type_cast

from nomarr.components.ml.calibration_state_comp import (
    compute_convergence_status,
    compute_reconciliation_info,
)
from nomarr.components.ml.ml_discovery_comp import discover_heads
from nomarr.helpers.time_helper import now_ms
from nomarr.workflows.calibration.generate_calibration_wf import (
    generate_histogram_calibration_wf,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


@dataclass
class CalibrationConfig:
    """Configuration for CalibrationService."""

    models_dir: str
    namespace: str
    thresholds: dict[str, float] = field(default_factory=dict)
    calibrate_heads: bool = False  # Whether calibration features are enabled


class CalibrationService:
    """Service for orchestrating calibration generation.

    Thin wrapper that provides DI to the calibration workflow.
    All domain logic lives in workflows.calibration_generation.
    """

    def __init__(
        self,
        db: Database,
        cfg: CalibrationConfig,
    ) -> None:
        """Initialize calibration service.

        Args:
            db: Database instance
            cfg: Calibration configuration

        """
        self._db = db
        self.cfg = cfg
        self._generation_thread: threading.Thread | None = None
        self._generation_result: dict[str, Any] | None = None
        self._generation_error: Exception | None = None
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {}

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
            self._db, result.get("global_version"),
        )
        result["requires_reconciliation"] = reconciliation_info["requires_reconciliation"]
        result["affected_libraries"] = reconciliation_info["affected_libraries"]

        return result

    def start_histogram_calibration_background(self) -> None:
        """Start histogram-based calibration generation in background thread.

        Follows threading pattern from design document.
        Thread-safe: can check is_generation_running() and get_generation_result().
        """
        if self._generation_thread and self._generation_thread.is_alive():
            logger.warning("[CalibrationService] Calibration generation already running")
            return

        # Reset state
        self._generation_result = None
        self._generation_error = None
        self._clear_progress()

        # Start background thread
        self._generation_thread = threading.Thread(
            target=self._run_histogram_generation,
            name="CalibrationGeneration",
            daemon=False,
        )
        self._generation_thread.start()
        logger.info("[CalibrationService] Started histogram calibration generation in background")

    # -- Threading infrastructure (NOT domain logic; see services.instructions.md) --

    def _update_progress(self, **kwargs: int | float | str | None) -> None:
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

    def _run_histogram_generation(self) -> None:
        """Background thread: run histogram calibration generation."""
        try:
            logger.info("[CalibrationService] Background generation started")
            result = self.generate_histogram_calibration()
            self._generation_result = result
            logger.info(
                f"[CalibrationService] Background generation completed: "
                f"{result['heads_success']} success, {result['heads_failed']} failed",
            )
        except Exception as e:
            logger.error(f"[CalibrationService] Background generation failed: {e}", exc_info=True)
            self._generation_error = e
        finally:
            self._clear_progress()

    def is_generation_running(self) -> bool:
        """Check if histogram calibration generation is currently running."""
        return self._generation_thread is not None and self._generation_thread.is_alive()

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

    def get_generation_status(self) -> dict[str, Any]:
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

    def get_generation_progress(self) -> dict[str, Any]:
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
                "total_heads": progress.get("total_heads", 0),
                "completed_heads": 0,  # Not meaningful during generation
                "remaining_heads": 0,
                "last_updated": None,
                "is_running": True,
                "current_head": progress.get("current_head"),
                "current_head_index": progress.get("current_head_index"),
            }

        # Not running: fall back to DB query for head completion counts
        heads = discover_heads(self.cfg.models_dir)
        total_heads = len(heads)

        # Count heads with recent calibration_state (within 24 hours)
        recent_threshold = now_ms().value - (24 * 60 * 60 * 1000)

        cursor = self._db.db.aql.execute(
            """
            RETURN COUNT(
                FOR c IN calibration_state
                    FILTER c.updated_at >= @threshold
                    RETURN 1
            )
            """,
            bind_vars=type_cast("dict[str, Any]", {"threshold": recent_threshold}),
        )
        completed = next(cursor, 0)  # type: ignore

        # Get most recent calibration timestamp
        cursor = self._db.db.aql.execute(
            """
            FOR c IN calibration_state
                SORT c.updated_at DESC
                LIMIT 1
                RETURN c.updated_at
            """,
        )
        last_updated = next(cursor, None)  # type: ignore

        return {
            "total_heads": total_heads,
            "completed_heads": completed,
            "remaining_heads": total_heads - completed,
            "last_updated": last_updated,
            "is_running": False,
            "current_head": None,
            "current_head_index": None,
        }

    def get_calibration_history(
        self,
        calibration_key: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get calibration convergence history.

        NOTE: This method uses the legacy calibration_history collection from
        progressive calibration. Will be deprecated in favor of histogram visualization.

        Args:
            calibration_key: Specific head (e.g., "effnet-20220825:mood_happy") or None for all
            limit: Maximum snapshots to return per head

        Returns:
            {"calibration_key": [...snapshots...]} or {"all_heads": {key: [...snapshots...]}}

        """
        if calibration_key:
            history = self._db.calibration_history.get_history(
                calibration_key=calibration_key,
                limit=limit,
            )
            return {"calibration_key": calibration_key, "history": history}

        # Inline grouping logic (simplified from removed group_snapshots_by_head)
        recent = self._db.calibration_history.get_all_recent_snapshots(limit=limit * 10)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for snapshot in recent:
            key = snapshot["calibration_key"]
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(snapshot)
        for key in grouped:
            grouped[key] = sorted(grouped[key], key=lambda x: x["snapshot_at"], reverse=True)[:limit]
        return {"all_heads": grouped}

    def get_latest_convergence_status(self) -> dict[str, Any]:
        """Get latest convergence metrics for all heads."""
        return compute_convergence_status(self._db)


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
        state = self._db.calibration_state.get_calibration_state(model_key, head_name, label)
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
    #  Reconciliation Info

