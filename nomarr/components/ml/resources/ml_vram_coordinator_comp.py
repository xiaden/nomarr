"""VRAM promise coordinator component.

Provides fleet-aware VRAM coordination for multi-worker GPU model placement.
Before any model is loaded to GPU, the worker registers a promise here via
an atomic AQL fit-check. Stale promises (from crashed workers) are reaped
periodically so their reserved VRAM becomes available to other workers.

All four functions are stateless: the ``db`` argument carries all state.

Typical call sequence (executed in ml_onnx_cache or ml_onnx_base):
    1. register_vram_promise(db, worker_id, pid, model_path, promised_mb)
       -> True  => proceed to load the model on GPU
       -> False => fall back to CPU for this model
    2. (model is loaded and used)
    3. release_vram_promise(db, worker_id, model_path)  on unload
"""

from __future__ import annotations

import logging
from typing import Any

from nomarr.components.platform import resource_monitor_comp as _resource_monitor

logger = logging.getLogger(__name__)


def register_vram_promise(
    db: Any,
    worker_id: str,
    pid: int,
    model_path: str,
    promised_mb: float,
) -> bool:
    """Atomically register a VRAM promise if the model fits in available headroom.

    Queries current VRAM usage (fresh reading, telemetry cache reset), then
    calls the AQL fit-check transaction. Returns True only if the promise
    was inserted (model fits). Returns False if the GPU has insufficient
    headroom — the caller should fall back to CPU.

    Args:
        db:          Application database (must have ``vram_promises`` attribute).
        worker_id:   Worker identifier (e.g., ``“nomarr-tag:0”``).
        pid:         Worker OS PID.
        model_path:  Absolute path to the ONNX model file.
        promised_mb: VRAM required for this model (MB).

    Returns:
        True if registered (model may proceed to GPU), False if rejected.

    """
    # Force a fresh nvidia-smi reading; avoid stale TTL-cached values from a
    # previous model in the same warm cycle.
    _resource_monitor.reset_telemetry_cache()
    vram = _resource_monitor.get_vram_usage_mb()

    if vram.get("error"):
        logger.warning(
            "[vram_coordinator] nvidia-smi error for %s: %s — denying GPU placement",
            model_path,
            vram["error"],
        )
        return False

    total_mb: float = float(vram["total_mb"])
    used_mb: float = float(vram["used_mb"])

    registered: bool = db.vram_promises.try_register(  # type: ignore[union-attr]
        worker_id=worker_id,
        pid=pid,
        model_path=model_path,
        promised_mb=promised_mb,
        total_mb=total_mb,
        used_mb=used_mb,
    )

    if registered:
        logger.debug(
            "[vram_coordinator] Registered promise: worker=%s model=%s promised=%.0f MB (total=%.0f used=%.0f)",
            worker_id,
            model_path,
            promised_mb,
            total_mb,
            used_mb,
        )
    else:
        logger.debug(
            "[vram_coordinator] Rejected promise: worker=%s model=%s promised=%.0f MB "
            "(total=%.0f used=%.0f) — insufficient headroom",
            worker_id,
            model_path,
            promised_mb,
            total_mb,
            used_mb,
        )

    return registered


def release_vram_promise(
    db: Any,
    worker_id: str,
    model_path: str,
) -> None:
    """Release the VRAM promise for a specific worker+model pair.

    Should be called from ``BaseONNXModel.unload()`` when a GPU-resident
    model is evicted. Safe to call even if the promise no longer exists.

    Args:
        db:          Application database.
        worker_id:   Worker identifier.
        model_path:  Absolute path to the ONNX model file.

    """
    db.vram_promises.release(worker_id=worker_id, model_path=model_path)  # type: ignore[union-attr]
    logger.debug(
        "[vram_coordinator] Released promise: worker=%s model=%s",
        worker_id,
        model_path,
    )


def get_fleet_vram_state(
    db: Any,
) -> dict[str, Any]:
    """Return a snapshot of current fleet VRAM promises and live GPU telemetry.

    Intended for cache-ready log messages and health/diagnostic endpoints.

    Args:
        db: Application database.

    Returns:
        Dict with:
            ``promises``  - list of all current promise documents
            ``vram``      - result of ``get_vram_usage_mb()``
                            ({"used_mb": int, "total_mb": int, "error": str|None})

    """
    promises: list[dict[str, Any]] = db.vram_promises.get_all()  # type: ignore[union-attr]
    vram = _resource_monitor.get_vram_usage_mb()
    return {"promises": promises, "vram": vram}


def release_worker_promises(
    db: Any,
    worker_id: str,
) -> int:
    """Release all VRAM promises held by a specific worker.

    Called by the worker owner (``WorkerSystemService``) when a worker is
    declared dead or permanently failed, and at graceful shutdown.  Also
    called by the worker itself at startup to clear stale promises from a
    previous crash of the same ``worker_id``.

    Safe to call even if no promises exist for the worker (no-op).

    Args:
        db:        Application database.
        worker_id: Worker identifier (e.g., ``"nomarr-tag:0"``).

    Returns:
        Number of promise documents removed.

    """
    removed: int = db.vram_promises.release_all_for_worker(worker_id=worker_id)  # type: ignore[union-attr]
    if removed:
        logger.info(
            "[vram_coordinator] Released %d promise(s) for worker %s",
            removed,
            worker_id,
        )
    return removed
