"""Workflow: drop and rebuild vector index on a cold tier.

No hot-to-cold promotion — data must already be fully in cold.
Use this when you want to update index parameters (nLists) without
waiting for new hot data to accumulate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import derive_embed_dim

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def rebuild_vector_index_workflow(
    db: Database,
    backbone_id: str,
    models_dir: str,
) -> None:
    """Drop and rebuild the vector index on an existing cold tier.

    Does not touch hot tier or perform any hot-to-cold drain.
    Cold tier must already exist and be populated.
    Vector indexes are per-backbone (no library_key needed).

    Args:
        db: Database instance.
        backbone_id: Backbone identifier (e.g., "discogs_effnet").
        models_dir: Path to ML models directory (for embed_dim derivation).

    Raises:
        ValueError: If backbone not found, embed_dim cannot be determined,
            or cold tier does not exist.
        RuntimeError: If index creation fails.

    """
    logger.info(
        "[rebuild index wf] Starting for backbone=%s",
        backbone_id,
    )

    embed_dim = derive_embed_dim(models_dir, backbone_id)
    logger.info("[rebuild index wf] embed_dim=%d for %s", embed_dim, backbone_id)

    with db.ml.transaction():
        db.ml.rebuild_vector_index(embed_dim)

    logger.info("[rebuild index wf] Completed for backbone=%s", backbone_id)
