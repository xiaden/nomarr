"""Vector store maintenance operations.

Provides primitives for hot/cold vector store promotion and index rebuilding.
Never called during bootstrap (maintenance workflow only).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.onnx.ml_discovery_comp import _resolve_embedding_graph

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def derive_embed_dim(models_dir: str, backbone_id: str) -> int:
    """Derive embedding dimension by probing the backbone ONNX model.

    Opens the backbone embedding graph with ``onnxruntime`` and inspects
    the output named ``"embeddings"`` for its last dimension.

    Args:
        models_dir: Path to ML models directory.
        backbone_id: Backbone identifier (e.g., ``"discogs_effnet"``).

    Returns:
        Embedding dimension (e.g., 1280 for effnet).

    Raises:
        ValueError: If backbone ONNX file not found or embed_dim cannot be determined.

    """
    embedding_graph = _resolve_embedding_graph(models_dir, backbone_id)
    if not embedding_graph:
        raise ValueError("No embedding graph found")

    try:
        import onnxruntime as ort

        session = ort.InferenceSession(embedding_graph, providers=["CPUExecutionProvider"])
        for output in session.get_outputs():
            if output.name == "embeddings":
                shape = output.shape
                if isinstance(shape, list) and len(shape) >= 2:
                    dim = shape[-1]
                    if isinstance(dim, int) and dim > 0:
                        return dim
    except (ImportError, RuntimeError) as exc:
        raise ValueError(f"Failed to probe embedding graph '{embedding_graph}'") from exc

    raise ValueError(
        f"Cannot determine embed_dim for backbone '{backbone_id}'. "
        "Ensure backbone ONNX model has output named 'embeddings' with valid shape."
    )


def drain_hot_to_cold(db: Database, backbone_id: str) -> int:
    """Drain hot embeddings to cold tier for a backbone via MlDb facade.

    Delegates to ``db.ml.index_backbone_embeddings`` which performs a single
    UPDATE to promote all hot-tier rows to cold for the given backbone.

    Args:
        db: Database handle.
        backbone_id: Backbone identifier.

    Returns:
        Number of rows drained from hot to cold.

    """
    with db.ml.transaction():
        return db.ml.index_backbone_embeddings(backbone_id)


def verify_hot_empty(db: Database, backbone_id: str) -> None:
    """Verify hot tier is empty after drain (completeness check).

    Queries embedding stats via the MlDb facade and raises if any hot
    rows remain for the given backbone.

    Args:
        db: Database handle.
        backbone_id: Backbone identifier.

    Raises:
        RuntimeError: If hot embeddings remain.

    """
    stats = db.ml.get_embedding_stats(backbone_id)
    hot_count = stats.get("hot_count", 0)
    if hot_count > 0:
        raise RuntimeError(
            f"Hot embeddings not empty after drain for backbone '{backbone_id}': "
            f"{hot_count} remain. This indicates drain operation failed or "
            f"concurrent writes occurred during promotion."
        )


def drop_cold_vector_index(db: Database) -> None:
    """Drop vector index from cold embeddings.

    PostgreSQL manages the partial HNSW index via schema migration — this
    delegates to the MlDb facade which is a no-op for PG.
    """
    db.ml.drop_vector_index()


def has_vector_index(db: Database, backbone_id: str) -> bool:
    """Check if the cold HNSW vector index exists.

    Args:
        db: Database handle.
        backbone_id: Backbone identifier.

    Returns:
        True if the cold HNSW index exists.

    """
    return db.ml.has_vector_index(backbone_id)


def build_cold_vector_index(db: Database, embed_dim: int) -> None:
    """Build vector index on cold embeddings.

    For PostgreSQL, this is a no-op — the partial HNSW index is created
    at schema time by the Alembic migration.

    Args:
        db: Database handle.
        embed_dim: Embedding dimension (from derive_embed_dim).

    """
    db.ml.build_vector_index(embed_dim)


def rebuild_cold_vector_index(db: Database, embed_dim: int) -> None:
    """Drop existing vector index and rebuild it.

    For PostgreSQL, this runs REINDEX CONCURRENTLY on the cold HNSW index
    via the MlDb facade.

    Args:
        db: Database handle.
        embed_dim: Embedding dimension.

    """
    with db.ml.transaction():
        db.ml.rebuild_vector_index(embed_dim)


def backfill_genres(db: Database, backbone_id: str) -> int:
    """Backfill genres on cold embeddings that predate genre enrichment.

    Delegates to the MlDb facade which counts embeddings with NULL genres
    for the given backbone. Full genre backfill requires joining with the
    songs tag data, which is outside MlDb's scope.

    Args:
        db: Database handle.
        backbone_id: Backbone identifier.

    Returns:
        Number of embeddings updated with genre data.

    """
    return db.ml.backfill_genres(backbone_id)
