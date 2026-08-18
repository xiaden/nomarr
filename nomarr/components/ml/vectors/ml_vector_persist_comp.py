"""Vector persistence component: build canonical pooled backbone embedding payloads.

The live vector write flows through the deferred-write aggregate
``db.ml.replace_song_inference_results`` scoped to ``(song_id, backbone)``. This
component no longer issues destructive DB writes itself; it derives the pooled
track-level embedding and returns the canonical vector payload that the
deferred-write path forwards to the aggregate. Because the aggregate deletes and
re-inserts only the ``(song_id, backbone)`` scope it is given, persisting one
backbone never erases another backbone's vectors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.vectors.ml_vector_pool_comp import get_embedding_dimension, pool_embedding_for_storage
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


def build_backbone_vector_payload(
    backbone: str,
    model_suite_hash: str,
    embed_dim: int,
    vector: list[float],
    num_segments: int,
) -> dict[str, Any]:
    """Build the canonical vector payload for the aggregate.

    The aggregate scopes replacement by ``(song_id, backbone)`` and persists the
    canonical payload keys: ``backbone_id``, ``model_id``, ``embedding_vector``
    (plus informational ``embed_dim``/``num_segments``).

    Args:
        backbone: Backbone model name — the canonical ``backbone_id``.
        model_suite_hash: Hash of the model suite that produced the embeddings.
        embed_dim: Embedding dimensionality of ``vector``.
        vector: Pooled track-level embedding vector.
        num_segments: Number of source segments pooled into ``vector``.

    Returns:
        Canonical vector payload ``{backbone_id, model_id, embedding_vector,
        embed_dim, num_segments}``.

    """
    return {
        "backbone_id": backbone,
        "model_id": model_suite_hash,
        "embedding_vector": list(vector),
        "embed_dim": embed_dim,
        "num_segments": num_segments,
    }


def persist_backbone_vector(
    backbone: str,
    embeddings_2d: np.ndarray,
    model_suite_hash: str,
    path: str,
) -> dict[str, Any] | None:
    """Derive the pooled track-level embedding and return its canonical payload.

    Pools the segment-level embeddings and builds the canonical vector payload
    (with the backbone as ``backbone_id``) that the deferred-write path sends to
    ``db.ml.replace_song_inference_results``. No DB write happens here — the
    aggregate owns the atomic ``(song_id, backbone)``-scoped replacement.

    Args:
        backbone: Backbone model name (the canonical ``backbone_id``).
        embeddings_2d: Shape ``[num_segments, embed_dim]`` backbone output.
        model_suite_hash: Hash of the model suite used to produce the embeddings.
        path: File path — used only for warning log messages on failure.

    Returns:
        Canonical vector payload on success, ``None`` on failure (warning logged).

    """
    t = internal_ms()
    try:
        vector = pool_embedding_for_storage(embeddings_2d)
        embed_dim = get_embedding_dimension(embeddings_2d)
        payload = build_backbone_vector_payload(
            backbone=backbone,
            model_suite_hash=model_suite_hash,
            embed_dim=embed_dim,
            vector=vector,
            num_segments=embeddings_2d.shape[0],
        )
        elapsed = internal_ms().value - t.value
        logger.debug(
            "[vectors] Derived %s vector: dim=%d, segments=%d (%.2f ms)",
            backbone,
            embed_dim,
            embeddings_2d.shape[0],
            elapsed,
        )
        return payload
    except (ValueError, RuntimeError, TypeError, OSError):
        logger.warning("[vectors] Failed to derive %s vector for %s", backbone, path, exc_info=True)
        return None
