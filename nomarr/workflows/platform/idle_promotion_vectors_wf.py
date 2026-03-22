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

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def idle_promotion_vectors_workflow(
    db: Database, worker_id: str, models_dir: str
) -> int:
    """Run hot\u2192cold vector promotion for all pending backbone+library pairs.

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
    from nomarr.components.ml.vectors.ml_vector_idle_promotion_comp import (
        compute_promotion_nlists,
        list_hot_vector_targets,
    )
    from nomarr.workflows.platform.promote_and_rebuild_vectors_wf import (
        promote_and_rebuild_workflow,
    )

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
    stale_locks = db.vector_promotion_locks.get_stale_locks(stale_after_ms=600_000)
    for stale_backbone, stale_library in stale_locks:
        db.vector_promotion_locks.force_release_lock(stale_backbone, stale_library)
        logger.warning(
            "[%s] Reaped stale promotion lock for %s__%s",
            worker_id,
            stale_backbone,
            stale_library,
        )

    # Step 3-4: Acquire lock, compute nlists, promote and rebuild
    promoted = 0
    for backbone_id, library_key in targets:
        if not db.vector_promotion_locks.try_acquire_lock(
            backbone_id, library_key, worker_id
        ):
            logger.debug(
                "[%s] Lock held for %s__%s \u2014 skipping",
                worker_id,
                backbone_id,
                library_key,
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
            promote_and_rebuild_workflow(
                db, backbone_id, library_key, nlists, models_dir
            )
            promoted += 1
        except Exception:
            logger.exception(
                "[%s] Promotion failed for %s__%s",
                worker_id,
                backbone_id,
                library_key,
            )
        finally:
            db.vector_promotion_locks.release_lock(
                backbone_id, library_key, worker_id
            )

    logger.info("[%s] Idle promotion complete: %d promoted", worker_id, promoted)
    return promoted
