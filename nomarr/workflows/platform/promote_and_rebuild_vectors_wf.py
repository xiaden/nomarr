"""Promote and rebuild vectors workflow.

Orchestrates hot → cold vector promotion with index rebuild. Prevents OOM
during active ML processing by deferring expensive HNSW maintenance to
scheduled maintenance windows.

Never runs during bootstrap (maintenance workflow only).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import derive_embed_dim

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def promote_and_rebuild_workflow(
    db: Database,
    backbone_id: str,
    library_key: str,
    nlists: int,
    models_dir: str,
) -> None:
    """Promote vectors from hot to cold and rebuild vector index.

    Convergent + idempotent: delegates all hot/cold mechanics to the persistence
    layer. Returns early if hot is already empty and cold has an index.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier (e.g., "discogs_effnet").
        library_key: ArangoDB ``_key`` of the library document.
        nlists: Number of HNSW graph lists for vector index.
        models_dir: Path to ML models directory.

    Raises:
        ValueError: If backbone not found or embed_dim cannot be determined.
        RuntimeError: If hot not empty after drain (completeness check fails).

    """
    logger.info(
        "[promote & rebuild] Starting for backbone: %s, library: %s (nlists=%d)",
        backbone_id,
        library_key,
        nlists,
    )

    embed_dim = derive_embed_dim(models_dir, backbone_id)
    logger.info("[promote & rebuild] Derived embed_dim=%d for %s", embed_dim, backbone_id)

    drained = db.ml.index_library_embeddings(backbone_id, library_key, embed_dim, nlists)
    if drained == 0:
        logger.info("[promote & rebuild] Hot empty and cold indexed — nothing to do")
    else:
        logger.info(
            "[promote & rebuild] Drained %d documents and rebuilt index for %s/%s",
            drained,
            backbone_id,
            library_key,
        )

    logger.info(
        "[promote & rebuild] Completed successfully for %s (library=%s)",
        backbone_id,
        library_key,
    )
