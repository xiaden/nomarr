"""Vector persistence component: store pooled backbone embeddings in the database."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.ml.vectors.ml_vector_pool_comp import get_embedding_dimension, pool_embedding_for_storage
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def persist_backbone_vector(
    db: Database,
    file_id: str,
    backbone: str,
    embeddings_2d: np.ndarray,
    model_suite_hash: str,
    path: str,
) -> float | None:
    """Persist a pooled track-level embedding vector for one backbone.

    Pools the segment-level embeddings, writes the result to the appropriate
    vector collection, and returns elapsed milliseconds.

    Args:
        db: Database instance.
        file_id: library_files document _id.
        backbone: Backbone model name (used to select the vector collection).
        embeddings_2d: Shape ``[num_segments, embed_dim]`` backbone output.
        model_suite_hash: Hash of the model suite used to produce the embeddings.
        path: File path — used only for warning log messages on failure.

    Returns:
        Elapsed milliseconds on success, ``None`` on failure (warning logged).
    """
    t = internal_ms()
    try:
        vector = pool_embedding_for_storage(embeddings_2d)
        embed_dim = get_embedding_dimension(embeddings_2d)
        ops = db.register_vectors_track_backbone(backbone)
        ops.upsert_vector(
            file_id=file_id,
            model_suite_hash=model_suite_hash,
            embed_dim=embed_dim,
            vector=vector,
            num_segments=embeddings_2d.shape[0],
        )
        elapsed = internal_ms().value - t.value
        logger.debug(
            "[processor] Persisted %s vector: dim=%d, segments=%d",
            backbone,
            embed_dim,
            embeddings_2d.shape[0],
        )
        return elapsed
    except Exception:
        logger.warning("[processor] Failed to persist %s vector for %s", backbone, path, exc_info=True)
        return None
