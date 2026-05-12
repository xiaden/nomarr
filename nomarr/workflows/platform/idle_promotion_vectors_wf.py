"""Idle vector promotion workflow.

Automatically promotes hot vectors to cold collections and rebuilds HNSW
indexes when a discovery worker is idle.  Orchestrates component functions
and the promote-and-rebuild workflow.

Thread safety
-------------
The ``Database`` instance passed here is the same object used by the worker's
main loop.  This is safe because python-arango uses HTTP connection pooling
that is thread-safe within a single process.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
    compute_promotion_nlists,
    list_hot_vector_targets,
)
from nomarr.components.platform import locks_comp
from nomarr.workflows.platform.promote_and_rebuild_vectors_wf import promote_and_rebuild_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def idle_promotion_vectors_workflow(db: Database, worker_id: str, models_dir: str) -> int:
    """Run hot→cold vector promotion for all pending backbone+library pairs.

    Intended to be called from a background thread when the discovery worker
    is idle.  Coordinates with other workers via DB-level locks.

    Steps:
    1. Find backbone+library pairs with pending hot vectors.
    2. Reap stale locks (crashed workers, >10 min).
    3. For each target, attempt to acquire lock.
    4. If acquired, compute nlists, promote and rebuild (lock always released).

    Args:
        db: Database instance (thread-safe via python-arango pooling).
        worker_id: Worker identifier for lock ownership.
        models_dir: Root directory containing model folders.

    Returns:
        Number of backbone+library pairs successfully promoted.

    """
    # Step 1: Find targets
    targets = list_hot_vector_targets(db, models_dir)
    if not targets:
        logger.debug("[%s] No hot vectors pending promotion", worker_id)
        return 0

    logger.info(
        "[%s] Found %d backbone+library pairs with hot vectors",
        worker_id,
        len(targets),
    )

    # Step 2: Reap stale locks (crashed workers, >10 minutes)
    locks_comp.reap_stale_locks(db, worker_id, stale_after_ms=600_000)

    # Step 3-4: Acquire lock, compute nlists, promote and rebuild
    promoted = 0
    ttl_seconds = 1800  # 30 minutes
    for backbone_id, library_key in targets:
        resource_id = f"{backbone_id}__{library_key}"
        lock_reference = locks_comp.make_lock_reference("vector_promotion", resource_id)
        if not locks_comp.acquire_distributed_lock(db, "vector_promotion", resource_id, worker_id, ttl_seconds):
            logger.debug(
                "[%s] Lock held for %s — skipping",
                worker_id,
                lock_reference,
            )
            continue

        try:
            nlists = compute_promotion_nlists(db, backbone_id, library_key)
            logger.info(
                "[%s] Promoting %s__%s (nlists=%d)",
                worker_id,
                backbone_id,
                library_key,
                nlists,
            )
            promote_and_rebuild_workflow(db, backbone_id, library_key, nlists, models_dir)
            promoted += 1
        except Exception:
            logger.exception(
                "[%s] Promotion failed for %s__%s",
                worker_id,
                backbone_id,
                library_key,
            )
        finally:
            locks_comp.release_distributed_lock(db, "vector_promotion", resource_id, worker_id)

    logger.info("[%s] Idle promotion complete: %d promoted", worker_id, promoted)
    return promoted
