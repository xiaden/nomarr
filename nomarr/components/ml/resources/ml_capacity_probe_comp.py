"""ML Capacity Probe component for GPU/CPU adaptive resource management.

Performs one-time measurement of per-worker resource consumption for admission control.
Runs once per model_set_hash (not per-worker, not on every startup).

Per GPU_REFACTOR_PLAN.md Section 7:
- Runs once per model_set_hash
- Protected by DB lock to prevent concurrent probes
- Measures VRAM (per-PID via nvidia-smi) and RAM (RSS via psutil)
- Results stored as measured_backbone_vram_mb and estimated_worker_ram_mb
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.components.ml.onnx.ml_cache import ONNXModelCache
from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db
from nomarr.components.platform.resource_monitor_comp import (
    check_nvidia_gpu_capability,
    get_ram_usage_mb,
    get_vram_usage_for_pid_mb,
)
from nomarr.helpers.time_helper import internal_ms, now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Probe configuration
PROBE_POLL_INTERVAL_S = 5000  # Interval to poll for completed probe
PROBE_TIMEOUT_S = 120000  # Timeout waiting for another worker's probe
CONSERVATIVE_BACKBONE_VRAM_MB = 8192  # Default if probe fails (EffNet worst case)
CONSERVATIVE_WORKER_RAM_MB = 4096  # Default if probe fails
PROBE_LOCK_TTL_MS = 1800 * 1000


@dataclass
class CapacityEstimate:
    """Result from ML capacity probe.

    Attributes:
        model_set_hash: Hash identifying the model configuration
        measured_backbone_vram_mb: VRAM used by backbone model (0 if CPU-only)
        estimated_worker_ram_mb: RAM used by worker (heads + overhead)
        gpu_capable: True if GPU is available
        is_conservative: True if using fallback values (probe failed/timed out)

    """

    model_set_hash: str
    measured_backbone_vram_mb: int
    estimated_worker_ram_mb: int
    gpu_capable: bool
    is_conservative: bool = False


def _probe_lock_reference(model_set_hash: str) -> str:
    """Build the unique document_reference used for capacity probe locks."""
    return f"capacity_probe:{model_set_hash}"


def _try_acquire_probe_lock(db: Database, model_set_hash: str, worker_id: str) -> bool:
    """Acquire the constructor-backed probe lock for one model set."""
    reference = _probe_lock_reference(model_set_hash)
    now_value = float(now_ms().value)
    existing = db.locks.get(document_reference=reference)
    if isinstance(existing, dict):
        existing_expires_at = float(existing.get("expires_at", 0.0))
        if existing_expires_at >= now_value and existing.get("holder") != worker_id:
            return False
        db.locks.delete(document_reference=reference)

    try:
        db.locks.insert(
            [
                {
                    "document_reference": reference,
                    "lock_type": "capacity_probe",
                    "holder": worker_id,
                    "expires_at": now_value + float(PROBE_LOCK_TTL_MS),
                    "acquired_at": now_value,
                    "status": "active",
                }
            ],
        )
    except DocumentInsertError:
        return False

    return True


def _get_probe_lock_status(db: Database, model_set_hash: str) -> dict[str, Any] | None:
    """Return the lock document for a capacity probe, if present."""
    return cast("dict[str, Any] | None", db.locks.get(document_reference=_probe_lock_reference(model_set_hash)))


def _complete_probe_lock(db: Database, model_set_hash: str) -> None:
    """Mark a capacity probe lock complete without changing its reference."""
    reference = _probe_lock_reference(model_set_hash)
    existing = db.locks.get(document_reference=reference)
    if not isinstance(existing, dict):
        return

    updated = dict(existing)
    updated.pop("_id", None)
    updated["document_reference"] = reference
    updated["status"] = "complete"
    db.locks.upsert(
        document_reference=reference,
        fields={key: value for key, value in updated.items() if key != "document_reference"},
    )


def _release_probe_lock(db: Database, model_set_hash: str) -> None:
    """Delete the lock document for a capacity probe."""
    db.locks.delete(document_reference=_probe_lock_reference(model_set_hash))


def _get_capacity_estimate(db: Database, model_set_hash: str) -> dict[str, Any] | None:
    """Read the persisted capacity estimate document for one model set."""
    return cast("dict[str, Any] | None", db.ml_capacity.get(model_set_hash=model_set_hash))


def _save_capacity_estimate(
    db: Database,
    model_set_hash: str,
    measured_backbone_vram_mb: int,
    estimated_worker_ram_mb: int,
    probe_duration_s: float,
    probed_by_worker: str,
) -> None:
    """Persist or refresh the capacity estimate for one model set."""
    existing = _get_capacity_estimate(db, model_set_hash)
    timestamp = now_ms().value
    payload: dict[str, Any] = {
        "model_set_hash": model_set_hash,
        "measured_backbone_vram_mb": measured_backbone_vram_mb,
        "estimated_worker_ram_mb": estimated_worker_ram_mb,
        "probe_duration_s": probe_duration_s,
        "probed_by": probed_by_worker,
        "created_at": timestamp if existing is None else existing.get("created_at"),
        "updated_at": None if existing is None else timestamp,
    }
    db.ml_capacity.upsert(
        model_set_hash=model_set_hash,
        fields={key: value for key, value in payload.items() if key != "model_set_hash"},
    )


def _delete_capacity_estimate(db: Database, model_set_hash: str) -> None:
    """Delete the stored capacity estimate and any related probe lock."""
    db.ml_capacity.delete(model_set_hash=model_set_hash)
    _release_probe_lock(db, model_set_hash)


def compute_model_set_hash(models_dir: str) -> str:
    """Compute a hash of the model set for capacity probe invalidation.

    The hash changes when:
    - Model files are added/removed
    - Model file sizes change (indicates different model version)

    Args:
        models_dir: Path to the models directory

    Returns:
        Hex digest hash of the model set

    """
    hasher = hashlib.sha256()

    # Walk the models directory and hash file paths + sizes
    try:
        for root, _dirs, files in sorted(os.walk(models_dir)):
            for filename in sorted(files):
                if filename.endswith(".onnx"):
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, models_dir)
                    file_size = os.path.getsize(filepath)
                    hasher.update(f"{rel_path}:{file_size}".encode())
    except Exception as e:
        logger.warning("[ml_capacity_probe] Error computing model hash: %s", e)
        # Use timestamp-based hash as fallback
        hasher.update(f"fallback:{now_ms()}".encode())

    return hasher.hexdigest()[:16]  # Use first 16 chars


def get_or_run_capacity_probe(
    db: Database,
    models_dir: str,
    worker_id: str,
    ram_detection_mode: str = "auto",
) -> CapacityEstimate:
    """Get existing capacity estimate or run a new probe.

    Per GPU_REFACTOR_PLAN.md Section 7:
    - Runs once per model_set_hash
    - Protected by DB lock (only one worker probes at a time)
    - Other workers poll for completion (5s interval, 120s timeout)

    Args:
        db: Database instance
        models_dir: Path to models directory
        worker_id: ID of the calling worker
        ram_detection_mode: RAM detection mode (auto/cgroup/host)

    Returns:
        CapacityEstimate with probe results

    """
    model_set_hash = compute_model_set_hash(models_dir)
    gpu_capable = check_nvidia_gpu_capability()

    # Check for existing estimate
    existing = _get_capacity_estimate(db, model_set_hash)
    if existing is not None:
        logger.debug(
            "[ml_capacity_probe] Using cached estimate for hash=%s (vram=%dMB, ram=%dMB)",
            model_set_hash,
            existing["measured_backbone_vram_mb"],
            existing["estimated_worker_ram_mb"],
        )
        return CapacityEstimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=existing["measured_backbone_vram_mb"],
            estimated_worker_ram_mb=existing["estimated_worker_ram_mb"],
            gpu_capable=gpu_capable,
            is_conservative=False,
        )

    # Try to acquire probe lock
    lock_acquired = _try_acquire_probe_lock(db, model_set_hash, worker_id)

    if lock_acquired:
        # This worker will perform the probe
        logger.info(
            "[ml_capacity_probe] Acquired probe lock for hash=%s, starting probe...",
            model_set_hash,
        )
        return _run_capacity_probe(
            db=db,
            model_set_hash=model_set_hash,
            models_dir=models_dir,
            worker_id=worker_id,
            gpu_capable=gpu_capable,
            ram_detection_mode=ram_detection_mode,
        )

    # Another worker owns the lock - poll for completion
    logger.info("[ml_capacity_probe] Probe lock owned by another worker, polling for result...")
    return _wait_for_probe_completion(
        db=db,
        model_set_hash=model_set_hash,
        gpu_capable=gpu_capable,
    )


def _run_capacity_probe(
    db: Database,
    model_set_hash: str,
    models_dir: str,
    worker_id: str,
    gpu_capable: bool,
    ram_detection_mode: str,
) -> CapacityEstimate:
    """Execute the actual capacity probe.

    Measures resource usage by processing one file with a backbone model.

    Args:
        db: Database instance
        model_set_hash: Hash of the model set
        models_dir: Path to models directory
        worker_id: Worker performing the probe
        gpu_capable: Whether GPU is available
        ram_detection_mode: RAM detection mode

    Returns:
        CapacityEstimate with measured values

    """
    probe_start = internal_ms()

    try:
        # Measure current RAM before loading models
        ram_before = get_ram_usage_mb(ram_detection_mode)
        ram_before_mb = ram_before["used_mb"]

        # Measure VRAM before loading models (if GPU capable)
        vram_before_mb = 0
        if gpu_capable:
            vram_before_mb = get_vram_usage_for_pid_mb(os.getpid())

        # Import ML components to trigger model loading
        # This simulates the actual resource usage during processing
        # Discover heads to understand model requirements
        heads = discover_heads_no_db(models_dir)
        if not heads:
            logger.warning(
                "[ml_capacity_probe] No heads found in %s, using conservative estimates",
                models_dir,
            )
            _release_probe_lock(db, model_set_hash)
            return CapacityEstimate(
                model_set_hash=model_set_hash,
                measured_backbone_vram_mb=CONSERVATIVE_BACKBONE_VRAM_MB if gpu_capable else 0,
                estimated_worker_ram_mb=CONSERVATIVE_WORKER_RAM_MB,
                gpu_capable=gpu_capable,
                is_conservative=True,
            )

        # Get unique backbones
        backbones = {h.backbone for h in heads}
        logger.info(
            "[ml_capacity_probe] Found %d heads across backbones: %s",
            len(heads),
            backbones,
        )

        # Warm up ONNX model cache to measure actual memory usage
        _probe_cache = ONNXModelCache(models_dir, "gpu" if gpu_capable else "cpu")
        _probe_cache.warm = True

        # Measure RAM after loading
        ram_after = get_ram_usage_mb(ram_detection_mode)
        ram_after_mb = ram_after["used_mb"]

        # Measure VRAM after loading (if GPU capable)
        vram_after_mb = 0
        if gpu_capable:
            vram_after_mb = get_vram_usage_for_pid_mb(os.getpid())

        # Calculate resource usage
        backbone_vram_mb = max(0, vram_after_mb - vram_before_mb)
        worker_ram_mb = max(0, ram_after_mb - ram_before_mb)

        # Add buffer for heads (~2GB typical) if not already included
        if worker_ram_mb < 1024:
            worker_ram_mb = max(worker_ram_mb, 2048)

        probe_duration = internal_ms().value - probe_start.value

        logger.info(
            "[ml_capacity_probe] Probe complete: backbone_vram=%dMB, worker_ram=%dMB (%.1fms)",
            backbone_vram_mb,
            worker_ram_mb,
            probe_duration,
        )

        # Persist results
        _save_capacity_estimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=backbone_vram_mb,
            estimated_worker_ram_mb=worker_ram_mb,
            probe_duration_s=probe_duration,
            probed_by_worker=worker_id,
            db=db,
        )

        # Mark lock as complete
        _complete_probe_lock(db, model_set_hash)

        return CapacityEstimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=backbone_vram_mb,
            estimated_worker_ram_mb=worker_ram_mb,
            gpu_capable=gpu_capable,
            is_conservative=False,
        )

    except Exception as e:
        logger.exception("[ml_capacity_probe] Probe failed: %s", e)
        # Release lock on failure so another worker can try
        _release_probe_lock(db, model_set_hash)

        # Return conservative estimates
        return CapacityEstimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=CONSERVATIVE_BACKBONE_VRAM_MB if gpu_capable else 0,
            estimated_worker_ram_mb=CONSERVATIVE_WORKER_RAM_MB,
            gpu_capable=gpu_capable,
            is_conservative=True,
        )


def _wait_for_probe_completion(
    db: Database,
    model_set_hash: str,
    gpu_capable: bool,
) -> CapacityEstimate:
    """Wait for another worker's probe to complete.

    Polls the database at PROBE_POLL_INTERVAL_S until completion or timeout.

    Args:
        db: Database instance
        model_set_hash: Hash of the model set
        gpu_capable: Whether GPU is available

    Returns:
        CapacityEstimate with results or conservative fallback

    """
    start_time = internal_ms().value
    deadline = start_time + PROBE_TIMEOUT_S

    while internal_ms().value < deadline:
        # Check for completed estimate
        estimate = _get_capacity_estimate(db, model_set_hash)
        if estimate is not None:
            logger.info(
                "[ml_capacity_probe] Got probe result from another worker (vram=%dMB, ram=%dMB)",
                estimate["measured_backbone_vram_mb"],
                estimate["estimated_worker_ram_mb"],
            )
            return CapacityEstimate(
                model_set_hash=model_set_hash,
                measured_backbone_vram_mb=estimate["measured_backbone_vram_mb"],
                estimated_worker_ram_mb=estimate["estimated_worker_ram_mb"],
                gpu_capable=gpu_capable,
                is_conservative=False,
            )

        # Check if lock is still held
        lock = _get_probe_lock_status(db, model_set_hash)
        if lock is None:
            # Lock was released (probe failed), check for estimate one more time
            estimate = _get_capacity_estimate(db, model_set_hash)
            if estimate is not None:
                return CapacityEstimate(
                    model_set_hash=model_set_hash,
                    measured_backbone_vram_mb=estimate["measured_backbone_vram_mb"],
                    estimated_worker_ram_mb=estimate["estimated_worker_ram_mb"],
                    gpu_capable=gpu_capable,
                    is_conservative=False,
                )
            # Lock released but no estimate - use conservative
            break

        if lock.get("status") == "complete":
            # Probe completed but we missed the estimate query - retry
            continue

        time.sleep(PROBE_POLL_INTERVAL_S)

    # Timeout or lock released without estimate - use conservative fallback
    logger.warning("[ml_capacity_probe] Probe timeout/failure, using conservative estimates (max_workers=1)")
    return CapacityEstimate(
        model_set_hash=model_set_hash,
        measured_backbone_vram_mb=CONSERVATIVE_BACKBONE_VRAM_MB if gpu_capable else 0,
        estimated_worker_ram_mb=CONSERVATIVE_WORKER_RAM_MB,
        gpu_capable=gpu_capable,
        is_conservative=True,
    )


def invalidate_capacity_estimate(db: Database, models_dir: str) -> None:
    """Invalidate cached capacity estimate (e.g., when model set changes).

    Args:
        db: Database instance
        models_dir: Path to models directory

    """
    model_set_hash = compute_model_set_hash(models_dir)
    _delete_capacity_estimate(db, model_set_hash)
    logger.info("[ml_capacity_probe] Invalidated capacity estimate for hash=%s", model_set_hash)
