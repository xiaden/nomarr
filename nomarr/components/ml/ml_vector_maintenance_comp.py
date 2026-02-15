"""Vector store maintenance operations.

Provides primitives for hot/cold vector store promotion and index rebuilding.
Never called during bootstrap (maintenance workflow only).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def derive_embed_dim(models_dir: str, backbone_id: str) -> int:
    """Derive embedding dimension from backbone model metadata.

    Probes backbone sidecar JSON to extract embedding dimension from
    output schema. Single source of truth for embed_dim.

    Args:
        models_dir: Path to ML models directory.
        backbone_id: Backbone identifier (e.g., "discogs_effnet").

    Returns:
        Embedding dimension (e.g., 1280 for effnet).

    Raises:
        ValueError: If backbone not found or embed_dim cannot be determined.

    """
    try:
        from nomarr.components.ml.ml_discovery_comp import discover_heads

        heads = discover_heads(models_dir)
    except Exception as exc:
        raise ValueError(f"Failed to discover models in {models_dir}") from exc

    # Find any head for this backbone to access embedding_sidecar
    for head in heads:
        if head.backbone == backbone_id:
            if not head.embedding_sidecar:
                continue

            # Probe embedding dimension from outputs with output_purpose="embeddings"
            outputs = head.embedding_sidecar.outputs
            if outputs and isinstance(outputs, list):
                for output in outputs:
                    if (
                        isinstance(output, dict)
                        and output.get("output_purpose") == "embeddings"
                    ):
                        shape = output.get("shape")
                        if isinstance(shape, list) and len(shape) >= 2:
                            embed_dim = int(shape[-1])
                            if embed_dim > 0:
                                return embed_dim

    raise ValueError(
        f"Cannot determine embed_dim for backbone '{backbone_id}'. "
        "Ensure model sidecar has output with output_purpose='embeddings' and valid shape."
    )


def drain_hot_to_cold(db: DatabaseLike, backbone_id: str) -> int:
    """Drain all vectors from hot to cold collection (convergent UPSERT).

    Uses AQL UPSERT with unique _key to ensure convergent operation.
    Safe to run multiple times (idempotent via unique constraint).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.

    Returns:
        Number of documents drained from hot.

    Raises:
        Exception: If AQL execution fails.

    """
    hot_name = f"vectors_track_hot__{backbone_id}"
    cold_name = f"vectors_track_cold__{backbone_id}"

    if not db.has_collection(hot_name):
        raise ValueError(f"Hot collection '{hot_name}' does not exist")

    # Create cold collection if it doesn't exist yet (first drain)
    if not db.has_collection(cold_name):
        logger.info("Creating cold collection: %s", cold_name)
        db.create_collection(cold_name)

    # Count hot docs before drain
    hot_coll = db.collection(hot_name)
    hot_count = hot_coll.count()

    if hot_count == 0:  # type: ignore[operator]  # count() returns int in sync context
        return 0

    # Convergent UPSERT: unique _key prevents duplication
    cursor = db.aql.execute(
        f"""
        FOR doc IN {hot_name}
            UPSERT {{ _key: doc._key }}
            INSERT doc
            UPDATE doc
            IN {cold_name}
        RETURN NEW
        """
    )
    drained = len(list(cursor))  # type: ignore[arg-type]

    logger.info(
        "Drained %d documents from %s to %s",
        drained,
        hot_name,
        cold_name,
    )
    return drained


def verify_hot_empty(db: DatabaseLike, backbone_id: str) -> None:
    """Verify hot collection is empty after drain (completeness check).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.

    Raises:
        RuntimeError: If hot collection is not empty.

    """
    hot_name = f"vectors_track_hot__{backbone_id}"
    if not db.has_collection(hot_name):
        return  # Hot doesn't exist = empty

    hot_coll = db.collection(hot_name)
    hot_count = hot_coll.count()

    if hot_count > 0:  # type: ignore[operator]  # count() returns int in sync context
        raise RuntimeError(
            f"Hot collection '{hot_name}' not empty after drain: {hot_count} documents remain. "
            "This indicates drain operation failed or concurrent writes occurred during promotion."
        )


def drop_cold_vector_index(db: DatabaseLike, backbone_id: str) -> None:
    """Drop vector index from cold collection (free memory before drain).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.

    """
    cold_name = f"vectors_track_cold__{backbone_id}"
    if not db.has_collection(cold_name):
        return  # Cold doesn't exist yet

    cold_coll = db.collection(cold_name)
    existing_indexes = cold_coll.indexes()

    for idx in existing_indexes:  # type: ignore[union-attr]
        if idx.get("type") == "vector":
            idx_id = idx.get("id")
            if idx_id:
                logger.info("Dropping vector index %s from %s", idx_id, cold_name)
                cold_coll.delete_index(idx_id)  # type: ignore[attr-defined]
                return


def has_vector_index(db: DatabaseLike, backbone_id: str) -> bool:
    """Check if cold collection has a vector index.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.

    Returns:
        True if cold collection has vector index, False otherwise.

    """
    cold_name = f"vectors_track_cold__{backbone_id}"
    if not db.has_collection(cold_name):
        return False

    cold_coll = db.collection(cold_name)
    existing_indexes = cold_coll.indexes()

    return any(
        idx.get("type") == "vector" for idx in existing_indexes  # type: ignore[union-attr]
    )


def build_cold_vector_index(
    db: DatabaseLike,
    backbone_id: str,
    embed_dim: int,
    nlists: int,
) -> None:
    """Build vector index on cold collection.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        embed_dim: Embedding dimension (from derive_embed_dim).
        nlists: Number of HNSW graph lists (controls memory/accuracy tradeoff).

    Raises:
        ValueError: If cold collection doesn't exist.
        Exception: If index creation fails.

    """
    cold_name = f"vectors_track_cold__{backbone_id}"
    if not db.has_collection(cold_name):
        raise ValueError(
            f"Cold collection '{cold_name}' does not exist. "
            "Run drain_hot_to_cold first to create cold collection."
        )

    cold_coll = db.collection(cold_name)
    doc_count = cold_coll.count()  # type: ignore[assignment]  # count() returns int in sync context

    logger.info(
        "Building vector index on %s (dim=%d, nlists=%d, docs=%d)",
        cold_name,
        embed_dim,
        nlists,
        doc_count,
    )

    try:
        cold_coll.add_index(  # type: ignore[attr-defined]
            {
                "type": "vector",
                "fields": ["vector"],
                "params": {
                    "metric": "cosine",
                    "dimension": embed_dim,
                    "nLists": nlists,
                },
            },
        )
        logger.info("Vector index created successfully on %s", cold_name)
    except Exception as exc:
        logger.error(
            "Failed to create vector index on %s (dim=%d, nlists=%d)",
            cold_name,
            embed_dim,
            nlists,
            exc_info=True,
        )
        raise RuntimeError(
            f"Vector index creation failed on {cold_name}: {exc}"
        ) from exc
