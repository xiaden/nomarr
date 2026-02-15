"""Promote and rebuild vectors workflow.

Orchestrates hot → cold vector promotion with index rebuild. Prevents OOM
during active ML processing by deferring expensive HNSW maintenance to
scheduled maintenance windows.

Never runs during bootstrap (maintenance workflow only).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.ml_vector_maintenance_comp import (
    build_cold_vector_index,
    derive_embed_dim,
    drain_hot_to_cold,
    drop_cold_vector_index,
    has_vector_index,
    verify_hot_empty,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def promote_and_rebuild_workflow(
    db: Database,
    backbone_id: str,
    nlists: int,
    models_dir: str,
) -> None:
    """Promote vectors from hot to cold and rebuild vector index.

    Convergent + idempotent operation:
    - UPSERT semantics + unique _key prevent duplication
    - Safe to run multiple times
    - Early return if hot empty and cold has index (already done)

    Args:
        db: Database instance.
        backbone_id: Backbone identifier (e.g., "discogs_effnet").
        nlists: Number of HNSW graph lists for vector index.
        models_dir: Path to ML models directory.

    Raises:
        ValueError: If backbone not found or embed_dim cannot be determined.
        RuntimeError: If hot not empty after drain (completeness check fails).

    """
    logger.info(
        "[promote & rebuild] Starting for backbone: %s (nlists=%d)",
        backbone_id,
        nlists,
    )

    # Step 1: Derive embed_dim from model metadata (single source of truth)
    try:
        embed_dim = derive_embed_dim(models_dir, backbone_id)
        logger.info(
            "[promote & rebuild] Derived embed_dim=%d for %s",
            embed_dim,
            backbone_id,
        )
    except ValueError as exc:
        logger.error(
            "[promote & rebuild] Failed to derive embed_dim for %s: %s",
            backbone_id,
            exc,
        )
        raise

    # Step 2: Log starting state (hot count, cold count, index exists)
    # Use Database methods (hot for write, cold for read/search)
    hot_ops = db.register_vectors_track_backbone(backbone_id)
    cold_ops = db.get_vectors_track_cold(backbone_id)

    hot_count_before = hot_ops.count()  # type: ignore[assignment]  # count() returns int in sync context
    cold_count_before = cold_ops.count() if db.db.has_collection(f"vectors_track_cold__{backbone_id}") else 0  # type: ignore[assignment,operator]
    index_exists_before = has_vector_index(db.db, backbone_id)

    logger.info(
        "[promote & rebuild] Starting state: hot=%d, cold=%d, index_exists=%s",
        hot_count_before,
        cold_count_before,
        index_exists_before,
    )

    # Early return if hot empty and cold has index (idempotent)
    if hot_count_before == 0 and index_exists_before:  # type: ignore[operator]
        logger.info(
            "[promote & rebuild] Hot empty and cold has index — already done"
        )
        return

    # Step 3: Drop cold vector index if exists (free memory before drain)
    if index_exists_before:
        logger.info("[promote & rebuild] Dropping existing cold vector index")
        drop_cold_vector_index(db.db, backbone_id)

    # Step 4: Drain hot → cold (convergent UPSERT)
    drained_count = drain_hot_to_cold(db.db, backbone_id)
    logger.info(
        "[promote & rebuild] Drained %d documents from hot to cold",
        drained_count,
    )

    # Step 5: Verify hot is empty (completeness check)
    try:
        verify_hot_empty(db.db, backbone_id)
        logger.info("[promote & rebuild] Hot collection empty after drain ✓")
    except RuntimeError as exc:
        logger.error(
            "[promote & rebuild] Hot not empty after drain: %s",
            exc,
        )
        raise

    # Step 6: Build cold vector index
    logger.info(
        "[promote & rebuild] Building vector index (dim=%d, nlists=%d)",
        embed_dim,
        nlists,
    )
    build_cold_vector_index(db.db, backbone_id, embed_dim, nlists)

    # Step 7: Log completion state
    hot_count_after = hot_ops.count()  # type: ignore[assignment]  # count() returns int in sync context
    cold_count_after = cold_ops.count()  # type: ignore[assignment]
    index_exists_after = has_vector_index(db.db, backbone_id)

    logger.info(
        "[promote & rebuild] Completion state: hot=%d, cold=%d, index_exists=%s",
        hot_count_after,
        cold_count_after,
        index_exists_after,
    )
    logger.info(
        "[promote & rebuild] Completed successfully for %s",
        backbone_id,
    )
