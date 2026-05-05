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

import hashlib
import logging
from typing import Any

from nomarr.components.platform import resource_monitor_comp as _resource_monitor
from nomarr.helpers.time_helper import now_ms

logger = logging.getLogger(__name__)

_RESERVE_MB = 256.0


def _promise_key(worker_id: str, model_path: str) -> str:
    """Compute a stable key for a worker+model VRAM promise."""
    raw = f"{worker_id}:{model_path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_worker_promises(db: Any, worker_id: str) -> list[dict[str, Any]]:
    """Return all VRAM promises currently held by one worker."""
    return list(db.vram_promises.get(worker_id=worker_id, limit=None))  # type: ignore[union-attr]


def _get_all_promises(db: Any) -> list[dict[str, Any]]:
    """Return all VRAM promise documents via constructor-backed accessors."""
    worker_ids = [
        row["value"]
        for row in db.vram_promises.aggregate("worker_id", limit=db.vram_promises.count())
        if "value" in row
    ]  # type: ignore[union-attr]
    promises: list[dict[str, Any]] = []
    for current_worker_id in worker_ids:
        promises.extend(db.vram_promises.get(worker_id=current_worker_id, limit=None))  # type: ignore[union-attr]
    return promises


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

    promises = _get_all_promises(db)
    sum_promised = sum(float(promise.get("promised_mb", 0.0)) for promise in promises)
    free_mb = total_mb - used_mb
    headroom = free_mb - sum_promised - _RESERVE_MB
    if headroom < promised_mb:
        logger.debug(
            "[vram_coordinator] Rejected promise: worker=%s model=%s promised=%.0f MB "
            "(total=%.0f used=%.0f) — insufficient headroom",
            worker_id,
            model_path,
            promised_mb,
            total_mb,
            used_mb,
        )
        return False

    existing_ids = [
        promise["_id"] for promise in _get_worker_promises(db, worker_id) if promise.get("model_path") == model_path
    ]
    if existing_ids:
        db.vram_promises.delete(existing_ids)  # type: ignore[union-attr]

    db.vram_promises.insert(  # type: ignore[union-attr]
        [
            {
                "_key": _promise_key(worker_id, model_path),
                "worker_id": worker_id,
                "pid": pid,
                "model_path": model_path,
                "promised_mb": promised_mb,
                "total_mb": total_mb,
                "used_mb": used_mb,
                "last_seen_ms": now_ms().value,
            }
        ],
    )
    registered = True

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
    matching_ids = [
        promise["_id"] for promise in _get_worker_promises(db, worker_id) if promise.get("model_path") == model_path
    ]
    if matching_ids:
        db.vram_promises.delete(matching_ids)  # type: ignore[union-attr]
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
    promises = _get_all_promises(db)
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
    promises = _get_worker_promises(db, worker_id)
    removed = len(promises)
    if promises:
        db.vram_promises.delete([promise["_id"] for promise in promises])  # type: ignore[union-attr]
    if removed:
        logger.info(
            "[vram_coordinator] Released %d promise(s) for worker %s",
            removed,
            worker_id,
        )
    return removed
