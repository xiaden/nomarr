"""Idle vector promotion component.

Automatically promotes hot vectors to cold collections and rebuilds HNSW
indexes when a discovery worker is idle.  Called from a background thread
spawned by ``DiscoveryWorker.run()``.

Thread safety
-------------
The ``Database`` instance passed to functions in this module is the same
object used by the worker's main loop.  This is safe because python-arango
uses HTTP connection pooling that is thread-safe within a single process.
Each request gets its own connection from the pool.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def list_hot_vector_targets(
    db: Database, models_dir: str
) -> list[tuple[str, str]]:
    """Find all (backbone_id, library_key) pairs with pending hot vectors.

    Enumerates backbones from the filesystem and libraries from the database,
    then checks each combination for a non-empty hot collection.

    Args:
        db: Database instance.
        models_dir: Root directory containing model folders.

    Returns:
        List of ``(backbone_id, library_key)`` tuples where the hot
        collection exists and has at least one document.

    """
    from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones

    backbones = discover_backbones(models_dir)
    if not backbones:
        return []

    libraries = db.libraries.list_libraries()
    if not libraries:
        return []

    targets: list[tuple[str, str]] = []
    for backbone_id in backbones:
        for lib_doc in libraries:
            library_key: str = lib_doc["_key"]
            hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
            if not db.db.has_collection(hot_coll_name):  # type: ignore[union-attr]
                continue
            hot_ops = db.register_vectors_track_backbone(backbone_id, library_key)
            if hot_ops.count() > 0:
                targets.append((backbone_id, library_key))

    return targets


def _compute_nlists(db: Database, backbone_id: str, library_key: str) -> int:
    """Compute optimal nlists for a backbone+library pair.

    Reads per-library ``vector_group_size`` from the library document,
    falling back to the default of 15.  Sums hot and cold counts to
    determine total document count.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Optimal nlists value (10-4000).

    """
    from nomarr.helpers.vector_params_helper import compute_nlists

    # Read per-library group size (fallback to default 15)
    group_size = 15
    lib_doc = db.libraries.get_library(library_key)
    if lib_doc is not None:
        lib_group_size = lib_doc.get("vector_group_size")
        if lib_group_size is not None:
            group_size = int(lib_group_size)

    # Sum hot + cold counts
    hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"

    hot_count = 0
    if db.db.has_collection(hot_coll_name):  # type: ignore[union-attr]
        hot_count = db.register_vectors_track_backbone(backbone_id, library_key).count()

    cold_count = 0
    if db.db.has_collection(cold_coll_name):  # type: ignore[union-attr]
        cold_count = db.get_vectors_track_cold(backbone_id, library_key).count()

    return compute_nlists(hot_count + cold_count, group_size)


def run_idle_promotion(db: Database, worker_id: str, models_dir: str) -> int:
    """Run hot→cold vector promotion for all pending backbone+library pairs.

    Intended to be called from a background thread when the discovery worker
    is idle.  Coordinates with other workers via DB-level locks.

    Steps:
    1. Find backbone+library pairs with pending hot vectors.
    2. Reap stale locks (crashed workers, >10 min).
    3. For each target, attempt to acquire lock.
    4. If acquired, promote and rebuild (lock always released in finally).

    Args:
        db: Database instance (thread-safe via python-arango pooling).
        worker_id: Worker identifier for lock ownership.
        models_dir: Root directory containing model folders.

    Returns:
        Number of backbone+library pairs successfully promoted.

    """
    from nomarr.workflows.platform.promote_and_rebuild_vectors_wf import (
        promote_and_rebuild_workflow,
    )

    targets = list_hot_vector_targets(db, models_dir)
    if not targets:
        logger.debug("[%s] No hot vectors pending promotion", worker_id)
        return 0

    logger.info(
        "[%s] Found %d backbone+library pairs with hot vectors",
        worker_id,
        len(targets),
    )

    # Reap stale locks (crashed workers, >10 minutes)
    stale_locks = db.vector_promotion_locks.get_stale_locks(stale_after_ms=600_000)
    for stale_backbone, stale_library in stale_locks:
        db.vector_promotion_locks.force_release_lock(stale_backbone, stale_library)
        logger.warning(
            "[%s] Reaped stale promotion lock for %s__%s",
            worker_id,
            stale_backbone,
            stale_library,
        )

    promoted = 0
    for backbone_id, library_key in targets:
        if not db.vector_promotion_locks.try_acquire_lock(
            backbone_id, library_key, worker_id
        ):
            logger.debug(
                "[%s] Lock held for %s__%s — skipping",
                worker_id,
                backbone_id,
                library_key,
            )
            continue

        try:
            nlists = _compute_nlists(db, backbone_id, library_key)
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
