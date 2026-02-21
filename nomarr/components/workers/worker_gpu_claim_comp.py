"""GPU warmup claim component.

Provides a thin business-logic wrapper around GpuClaimOperations AQL layer.
Serializes GPU cache warming across multiple discovery worker processes:
one worker warms GPU at a time, others skip to CPU-only processing.
"""

import logging

from nomarr.persistence import Database

logger = logging.getLogger(__name__)

# Seconds without a heartbeat before a claim is considered stale.
# A crashed worker's claim becomes available after this timeout.
STALE_TIMEOUT_S = 60


def attempt_acquire_gpu_claim(db: Database, worker_id: str) -> bool:
    """Try to acquire exclusive GPU warmup claim.

    Succeeds if no other worker holds a fresh claim. Stale claims
    (>60s without heartbeat) are automatically stolen.

    Args:
        db: Application database instance.
        worker_id: Worker identifier (e.g., "worker:tag:0").

    Returns:
        True if this worker now holds the claim.

    """
    acquired = db.gpu_claims.acquire_claim(worker_id, stale_timeout_s=STALE_TIMEOUT_S)
    if acquired:
        logger.info("[%s] Acquired GPU warmup claim", worker_id)
    else:
        logger.info("[%s] GPU warmup claim held by another worker — processing CPU-only", worker_id)
    return acquired


def heartbeat_gpu_claim(db: Database, worker_id: str) -> bool:
    """Update heartbeat on a held GPU warmup claim.

    Returns False if the claim was lost (e.g., another worker stole
    a stale claim while this worker was busy processing). The worker
    can continue with its already-loaded cache but should not block
    other workers from acquiring the claim.

    Args:
        db: Application database instance.
        worker_id: Worker identifier that should hold the claim.

    Returns:
        True if heartbeat succeeded, False if claim was lost.

    """
    alive = db.gpu_claims.heartbeat_claim(worker_id)
    if not alive:
        logger.warning("[%s] GPU warmup claim was lost (stolen or expired)", worker_id)
    return alive


def release_gpu_claim(db: Database, worker_id: str) -> None:
    """Release a held GPU warmup claim.

    Safe to call even if this worker doesn't hold the claim (no-op).
    Called on cache eviction and on clean worker shutdown.

    Args:
        db: Application database instance.
        worker_id: Worker identifier releasing the claim.

    """
    released = db.gpu_claims.release_claim(worker_id)
    if released:
        logger.info("[%s] Released GPU warmup claim", worker_id)
