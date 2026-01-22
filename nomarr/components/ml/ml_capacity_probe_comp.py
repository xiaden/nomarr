"""
ML Capacity Probe component for GPU/CPU adaptive resource management.

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
from typing import TYPE_CHECKING

from nomarr.components.platform.resource_monitor_comp import (
    check_nvidia_gpu_capability,
    get_ram_usage_mb,
    get_vram_usage_for_pid_mb,
)
from nomarr.helpers.time_helper import internal_s, now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Probe configuration
PROBE_POLL_INTERVAL_S = 5.0  # Interval to poll for completed probe
PROBE_TIMEOUT_S = 120.0  # Timeout waiting for another worker's probe
CONSERVATIVE_BACKBONE_VRAM_MB = 8192  # Default if probe fails (EffNet worst case)
CONSERVATIVE_WORKER_RAM_MB = 4096  # Default if probe fails


@dataclass
class CapacityEstimate:
    """
    Result from ML capacity probe.

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


def compute_model_set_hash(models_dir: str) -> str:
    """
    Compute a hash of the model set for capacity probe invalidation.

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
                if filename.endswith((".pb", ".h5", ".json")):
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
    """
    Get existing capacity estimate or run a new probe.

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
    existing = db.ml_capacity.get_capacity_estimate(model_set_hash)
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
    lock_acquired = db.ml_capacity.try_acquire_probe_lock(model_set_hash, worker_id)

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
    """
    Execute the actual capacity probe.

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
    probe_start = internal_s()

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
        from nomarr.components.ml.ml_discovery_comp import discover_heads

        # Discover heads to understand model requirements
        heads = discover_heads(models_dir)
        if not heads:
            logger.warning(
                "[ml_capacity_probe] No heads found in %s, using conservative estimates",
                models_dir,
            )
            db.ml_capacity.release_probe_lock(model_set_hash)
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

        # Warm up backbone cache to measure actual VRAM usage
        from nomarr.components.ml.ml_cache_comp import warmup_predictor_cache

        warmup_predictor_cache(models_dir=models_dir, cache_idle_timeout=300)

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

        probe_duration = internal_s().value - probe_start.value

        logger.info(
            "[ml_capacity_probe] Probe complete: backbone_vram=%dMB, worker_ram=%dMB (%.1fs)",
            backbone_vram_mb,
            worker_ram_mb,
            probe_duration,
        )

        # Persist results
        db.ml_capacity.save_capacity_estimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=backbone_vram_mb,
            estimated_worker_ram_mb=worker_ram_mb,
            probe_duration_s=probe_duration,
            probed_by_worker=worker_id,
        )

        # Mark lock as complete
        db.ml_capacity.complete_probe_lock(model_set_hash)

        return CapacityEstimate(
            model_set_hash=model_set_hash,
            measured_backbone_vram_mb=backbone_vram_mb,
            estimated_worker_ram_mb=worker_ram_mb,
            gpu_capable=gpu_capable,
            is_conservative=False,
        )

    except Exception as e:
        logger.error("[ml_capacity_probe] Probe failed: %s", e)
        # Release lock on failure so another worker can try
        db.ml_capacity.release_probe_lock(model_set_hash)

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
    """
    Wait for another worker's probe to complete.

    Polls the database at PROBE_POLL_INTERVAL_S until completion or timeout.

    Args:
        db: Database instance
        model_set_hash: Hash of the model set
        gpu_capable: Whether GPU is available

    Returns:
        CapacityEstimate with results or conservative fallback
    """
    start_time = internal_s().value
    deadline = start_time + PROBE_TIMEOUT_S

    while internal_s().value < deadline:
        # Check for completed estimate
        estimate = db.ml_capacity.get_capacity_estimate(model_set_hash)
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
        lock = db.ml_capacity.get_probe_lock_status(model_set_hash)
        if lock is None:
            # Lock was released (probe failed), check for estimate one more time
            estimate = db.ml_capacity.get_capacity_estimate(model_set_hash)
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
    """
    Invalidate cached capacity estimate (e.g., when model set changes).

    Args:
        db: Database instance
        models_dir: Path to models directory
    """
    model_set_hash = compute_model_set_hash(models_dir)
    db.ml_capacity.delete_capacity_estimate(model_set_hash)
    logger.info("[ml_capacity_probe] Invalidated capacity estimate for hash=%s", model_set_hash)
