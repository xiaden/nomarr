"""VRAM promise coordinator component.

Provides fleet-aware VRAM coordination for multi-worker GPU model placement.
Before any model is loaded to GPU, the worker registers a promise here
after a fleet headroom fit-check (queries existing promises, sums
committed VRAM, rejects if the new model would exceed 90%% of total
GPU memory). Stale promises (from crashed workers) are reaped
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
from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.platform import resource_monitor_comp as _resource_monitor

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class FleetVramState(TypedDict):
    """Snapshot of fleet VRAM promises and GPU telemetry."""

    promises: list[dict[str, Any]]
    vram: dict[str, Any]


def _promise_key(worker_id: str, model_path: str) -> str:
    """Compute a stable key for a worker+model VRAM promise."""
    raw = f"{worker_id}:{model_path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def register_vram_promise(
    db: Database,
    worker_id: str,
    pid: int,
    model_path: str,
    promised_mb: float,
) -> bool:
    """Register a VRAM promise after a two-step fit-check.

    Performs two sequential validations before inserting the promise:

    1. **nvidia-smi availability** — forces a fresh telemetry reading
       (cache reset) and queries current GPU usage.  If nvidia-smi
       reports an error the promise is denied immediately.
    2. **Fleet headroom fit-check** — queries all existing promises from
       the database, sums their ``promised_mb``, and rejects the new
       promise when ``committed_mb + promised_mb`` would exceed 90%% of
       total GPU VRAM.  The 10%% headroom reserves capacity for driver
       overhead and memory fragmentation.

     Only when both checks pass is the promise inserted via
     ``db.app.promise_vram()``.

     Args:
         db:          Application database (must have ``app`` sub-facade
                      with VRAM promise methods).
        worker_id:   Worker identifier (e.g., ``"nomarr-tag:0"``).
        pid:         Worker OS PID.
        model_path:  Absolute path to the ONNX model file.
        promised_mb: VRAM required for this model (MB).

    Returns:
        True if the promise was registered and the model may proceed to
        GPU.  False in two distinct cases: (a) nvidia-smi returned an
        error and GPU state cannot be determined, or (b) fleet headroom
        is exhausted (adding this promise would exceed 90%% of total GPU
        VRAM).  The caller should fall back to CPU on False.

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

    # Fleet headroom fit-check: reject if adding this promise would exceed
    # 90% of total GPU VRAM (10% headroom for driver overhead/fragmentation).
    existing = db.app.list_vram_promises()
    committed_mb = sum(float(p.get("promised_mb", 0)) for p in existing)
    if committed_mb + promised_mb > total_mb * 0.90:
        logger.debug(
            "[vram_coordinator] Headroom exhausted: worker=%s model=%s promised=%.0f MB "
            "committed=%.0f MB total=%.0f MB (threshold=%.0f MB) — rejecting GPU placement",
            worker_id,
            model_path,
            promised_mb,
            committed_mb,
            total_mb,
            total_mb * 0.90,
        )
        return False

    with db.app.transaction():
        db.app.promise_vram(
            worker_id=worker_id,
            pid=pid,
            model_path=model_path,
            promised_mb=promised_mb,
            total_mb=total_mb,
            used_mb=used_mb,
        )
    registered = True

    # registered is always True here — rejection paths return False above.
    logger.debug(
        "[vram_coordinator] Registered promise: worker=%s model=%s promised=%.0f MB (total=%.0f used=%.0f)",
        worker_id,
        model_path,
        promised_mb,
        total_mb,
        used_mb,
    )

    return registered


def release_vram_promise(
    db: Database,
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
    with db.app.transaction():
        db.app.release_vram(worker_id=worker_id, model_path=model_path)
    logger.debug(
        "[vram_coordinator] Released promise: worker=%s model=%s",
        worker_id,
        model_path,
    )


def get_fleet_vram_state(
    db: Database,
) -> FleetVramState:
    """Return a snapshot of current fleet VRAM promises and live GPU telemetry.

    Intended for cache-ready log messages and health/diagnostic endpoints.

    Args:
        db: Application database.

    Returns:
        FleetVramState with ``promises`` list and ``vram`` telemetry snapshot.

    """
    promises: list[dict[str, Any]] = db.app.list_vram_promises()
    vram = _resource_monitor.get_vram_usage_mb()
    return FleetVramState(promises=promises, vram=vram)  # type: ignore[typeddict-item]


def release_worker_promises(
    db: Database,
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
    # Count promises before releasing (AppDb.release_all_for_worker returns None)
    promises = db.app.list_vram_promises()
    count = sum(1 for p in promises if p.get("worker_id") == worker_id)
    with db.app.transaction():
        db.app.release_all_for_worker(worker_id=worker_id)
    if count:
        logger.info(
            "[vram_coordinator] Released %d promise(s) for worker %s",
            count,
            worker_id,
        )
    return count
