"""Vector persistence component: store pooled backbone embeddings in the database."""

from __future__ import annotations

import hashlib
import logging
import math
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from nomarr.components.ml.vectors.ml_vector_pool_comp import get_embedding_dimension, pool_embedding_for_storage
from nomarr.components.ml.vectors.ml_vector_registry_comp import get_hot_namespace
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
    """Return the deterministic key for one persisted track vector."""
    return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()


def _normalize_vector(vector: list[float]) -> list[float]:
    """Return an L2-normalized copy of ``vector`` for cosine ANN search."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return list(vector)
    return [value / norm for value in vector]


def upsert_hot_track_vector(
    db: Database,
    file_id: str,
    backbone: str,
    model_suite_hash: str,
    embed_dim: int,
    vector: list[float],
    num_segments: int,
    library_key: str,
) -> str:
    """Upsert one pooled track vector into the hot collection.

    Builds the hot vector document for the given file and model suite,
    upserts it into the hot namespace for the selected backbone/library, and
    ensures the ``file_has_vectors`` edge points at the stored vector.

    Args:
        db: Database instance.
        file_id: Library file document ``_id``.
        backbone: Backbone model name used to select the hot vector namespace.
        model_suite_hash: Hash of the model suite that produced the vector.
        embed_dim: Embedding dimensionality of ``vector``.
        vector: Pooled track-level embedding vector.
        num_segments: Number of source segments pooled into ``vector``.
        library_key: ArangoDB ``_key`` of the owning library.

    Returns:
        The stored vector document ``_id``.

    Raises:
        RuntimeError: If the hot vector upsert does not return any document ids.

    """
    vector_key = _make_vector_key(file_id, model_suite_hash)
    vector_doc: dict[str, Any] = {
        "_key": vector_key,
        "file_id": file_id,
        "model_suite_hash": model_suite_hash,
        "embed_dim": embed_dim,
        "vector": list(vector),
        "vector_n": _normalize_vector(vector),
        "num_segments": num_segments,
        "created_at": internal_ms().value,
    }

    hot_ops = cast("Any", get_hot_namespace(db, backbone, library_key))
    vector_ids = cast("list[str]", hot_ops.upsert(_key=vector_key, fields=vector_doc))
    if not vector_ids:
        msg = f"Vector upsert returned no ids for file '{file_id}' in backbone '{backbone}'"
        raise RuntimeError(msg)

    vector_id = str(vector_ids[0])
    db.file_has_vectors.upsert(
        _from=file_id,
        _to=vector_id,
        fields={
            "_from": file_id,
            "_to": vector_id,
        },
    )
    return vector_id


def persist_backbone_vector(
    db: Database,
    file_id: str,
    backbone: str,
    embeddings_2d: np.ndarray,
    model_suite_hash: str,
    path: str,
    library_key: str,
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
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Elapsed milliseconds on success, ``None`` on failure (warning logged).
    """
    t = internal_ms()
    try:
        vector = pool_embedding_for_storage(embeddings_2d)
        embed_dim = get_embedding_dimension(embeddings_2d)
        upsert_hot_track_vector(
            db=db,
            file_id=file_id,
            backbone=backbone,
            model_suite_hash=model_suite_hash,
            embed_dim=embed_dim,
            vector=vector,
            num_segments=embeddings_2d.shape[0],
            library_key=library_key,
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
