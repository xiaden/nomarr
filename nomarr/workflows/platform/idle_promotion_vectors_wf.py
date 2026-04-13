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
from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.schema import Op

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _make_lock_reference(lock_type: str, resource_id: str) -> str:
    """Build the unique document reference used by the locks collection."""
    return f"{lock_type}:{resource_id}"


def _reap_stale_promotion_locks(db: Database, worker_id: str, stale_after_ms: int) -> None:
    """Delete stale promotion locks using constructor-backed field filters."""
    stale_threshold = float(now_ms().value - stale_after_ms)
    stale_locks = db.locks.acquired_at.get.in_(
        {Op.LT: stale_threshold},
        limit=db.locks.count(),
    )
    for lock in stale_locks:
        if lock.get("lock_type") != "vector_promotion":
            continue
        reference = str(lock["document_reference"])
        resource_id = reference.split(":", maxsplit=1)[1]
        db.locks.document_reference.delete(reference)
        logger.warning("[%s] Reaped stale promotion lock for %s", worker_id, resource_id)


def _acquire_lock(db: Database, lock_type: str, resource_id: str, holder: str, ttl_seconds: int) -> bool:
    """Acquire a lock using plain CRUD against the constructor namespace."""
    reference = _make_lock_reference(lock_type, resource_id)
    now = float(now_ms().value)
    expires_at = now + float(ttl_seconds * 1000)

    existing = cast("dict[str, Any] | None", db.locks.document_reference.get(reference))
    if existing is not None:
        existing_expires_at = float(existing.get("expires_at", 0.0))
        if existing_expires_at >= now and existing.get("holder") != holder:
            return False
        db.locks.document_reference.delete(reference)

    try:
        db.locks.insert(
            [
                {
                    "document_reference": reference,
                    "lock_type": lock_type,
                    "holder": holder,
                    "expires_at": expires_at,
                    "acquired_at": now,
                    "status": "active",
                }
            ],
        )
    except DocumentInsertError:
        return False

    return True


def _release_lock(db: Database, lock_type: str, resource_id: str, holder: str) -> bool:
    """Release a lock only when it is still owned by the requested holder."""
    reference = _make_lock_reference(lock_type, resource_id)
    existing = cast("dict[str, Any] | None", db.locks.document_reference.get(reference))
    if existing is None or existing.get("holder") != holder:
        return False
    return db.locks.document_reference.delete(reference) > 0


def idle_promotion_vectors_workflow(db: Database, worker_id: str, models_dir: str) -> int:
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
    _reap_stale_promotion_locks(db, worker_id, stale_after_ms=600_000)

    # Step 3-4: Acquire lock, compute nlists, promote and rebuild
    promoted = 0
    ttl_seconds = 1800  # 30 minutes
    for backbone_id, library_key in targets:
        resource_id = f"{backbone_id}__{library_key}"
        if not _acquire_lock(db, "vector_promotion", resource_id, worker_id, ttl_seconds):
            logger.debug(
                "[%s] Lock held for %s — skipping",
                worker_id,
                resource_id,
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
            _release_lock(db, "vector_promotion", resource_id, worker_id)

    logger.info("[%s] Idle promotion complete: %d promoted", worker_id, promoted)
    return promoted
