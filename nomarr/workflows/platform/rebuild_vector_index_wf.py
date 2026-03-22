"""Workflow: drop and rebuild vector index on a cold collection.

No hot-to-cold promotion — data must already be fully in cold.
Use this when you want to update index parameters (nLists) without
waiting for new hot data to accumulate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import (
    derive_embed_dim,
    rebuild_cold_vector_index,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def rebuild_vector_index_workflow(
    db: Database,
    backbone_id: str,
    library_key: str,
    nlists: int,
    models_dir: str,
) -> None:
    """Drop and rebuild the vector index on an existing cold collection.

    Does not touch hot collection or perform any hot-to-cold drain.
    Cold collection must already exist and be populated.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier (e.g., "discogs_effnet").
        library_key: ArangoDB ``_key`` of the library document.
        nlists: Number of Voronoi cells for the new index.
        models_dir: Path to ML models directory (for embed_dim derivation).

    Raises:
        ValueError: If backbone not found, embed_dim cannot be determined,
            or cold collection does not exist.
        RuntimeError: If index creation fails.

    """
    logger.info(
        "[rebuild index wf] Starting for backbone=%s library=%s nlists=%d",
        backbone_id,
        library_key,
        nlists,
    )

    embed_dim = derive_embed_dim(models_dir, backbone_id)
    logger.info(
        "[rebuild index wf] embed_dim=%d for %s", embed_dim, backbone_id
    )

    rebuild_cold_vector_index(db.db, backbone_id, library_key, embed_dim, nlists)

    logger.info("[rebuild index wf] Completed for backbone=%s library=%s", backbone_id, library_key)
