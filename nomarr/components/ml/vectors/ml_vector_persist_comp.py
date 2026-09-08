"""Vector persistence component: build canonical pooled backbone embedding commands.

The live vector write flows through the deferred-write aggregate
``db.ml.replace_song_inference_results`` scoped to ``(song, backbone)``. This
component no longer issues destructive DB writes itself; it derives the pooled
track-level embedding and returns the typed :class:`BackboneVectorWrite` command
that the deferred-write path forwards to the aggregate. Because the aggregate
deletes and re-inserts only the ``(song, backbone)`` scope it is given,
persisting one backbone never erases another backbone's vectors.

Pooling, segment counting, and model-suite-hash provenance remain component
responsibilities. Storage concerns (``embed_dim``, storage ids, tier,
timestamps) are intentionally absent from the typed command — persistence
derives ``embed_dim`` and owns all row mapping.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_pool_comp import get_embedding_dimension, pool_embedding_for_storage
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


def build_backbone_vector_payload(
    model_suite_hash: str,
    vector: list[float],
    num_segments: int,
) -> BackboneVectorWrite:
    """Build the typed vector command for one backbone.

    Returns a :class:`BackboneVectorWrite` carrying only application semantics.
    The aggregate scopes replacement by ``(song, backbone)``; ``embed_dim`` is
    derived by persistence as ``len(vector)``, and no storage keys
    (``backbone_id``/``model_id``/``embedding_vector``/``embed_dim``) cross this
    boundary.

    Args:
        model_suite_hash: Hash of the model suite that produced the embeddings.
        vector: Pooled track-level embedding vector.
        num_segments: Number of source segments pooled into ``vector``.

    Returns:
        Typed :class:`BackboneVectorWrite` command.
    """
    return BackboneVectorWrite(
        vector=tuple(vector),
        model_suite_hash=model_suite_hash,
        num_segments=num_segments,
    )


def persist_backbone_vector(
    backbone: str,
    embeddings_2d: np.ndarray,
    model_suite_hash: str,
    path: str,
) -> BackboneVectorWrite | None:
    """Derive the pooled track-level embedding and return its typed command.

    Pools the segment-level embeddings and builds the typed
    :class:`BackboneVectorWrite` command that the deferred-write path sends to
    ``db.ml.replace_song_inference_results`` (which scopes replacement to
    ``(song, backbone)``). No DB write happens here — the aggregate owns the
    atomic ``(song, backbone)``-scoped replacement.

    Args:
        backbone: Backbone model name (used only for logging).
        embeddings_2d: Shape ``[num_segments, embed_dim]`` backbone output.
        model_suite_hash: Hash of the model suite used to produce the embeddings.
        path: File path — used only for warning log messages on failure.

    Returns:
        Typed :class:`BackboneVectorWrite` command on success, ``None`` on
        failure (warning logged).

    """
    t = internal_ms()
    try:
        vector = pool_embedding_for_storage(embeddings_2d)
        embed_dim = get_embedding_dimension(embeddings_2d)
        num_segments = embeddings_2d.shape[0]
        command = build_backbone_vector_payload(
            model_suite_hash=model_suite_hash,
            vector=vector,
            num_segments=num_segments,
        )
        elapsed = internal_ms().value - t.value
        logger.debug(
            "[vectors] Derived %s vector: dim=%d, segments=%d (%.2f ms)",
            backbone,
            embed_dim,
            num_segments,
            elapsed,
        )
        return command
    except (ValueError, RuntimeError, TypeError, OSError):
        logger.warning("[vectors] Failed to derive %s vector for %s", backbone, path, exc_info=True)
        return None
