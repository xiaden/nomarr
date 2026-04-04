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
    from nomarr.components.ml.onnx.ml_discovery_comp import _resolve_embedding_graph

    embedding_graph = _resolve_embedding_graph(models_dir, backbone_id)
    if not embedding_graph:
        raise ValueError(f"No embedding graph found for backbone '{backbone_id}' in {models_dir}")

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
    except Exception as exc:
        raise ValueError(f"Failed to probe embedding graph '{embedding_graph}'") from exc

    raise ValueError(
        f"Cannot determine embed_dim for backbone '{backbone_id}'. "
        "Ensure backbone ONNX model has output named 'embeddings' with valid shape."
    )


def drain_hot_to_cold(db: DatabaseLike, backbone_id: str, library_key: str) -> int:
    """Drain all vectors from hot to cold collection (convergent UPSERT + truncate).

    Copies all documents from hot to cold via AQL UPSERT (idempotent by _key),
    then truncates hot. Safe to run multiple times.

    Each drained document is enriched with a ``genres`` field (``list[str]``)
    populated by joining ``song_has_tags`` edges and ``tags`` documents where
    ``tag.rel == "genre"`` for the document's file (resolved via edge).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of documents drained from hot.

    Raises:
        Exception: If AQL execution fails.

    """
    hot_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"

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

    # Convergent UPSERT with genre enrichment:
    # File_id resolved via edge traversal (file_id field dropped in migration)
    # Genres gathered per-doc via subquery joining song_has_tags → tags
    cursor = db.aql.execute(
        f"""
        FOR doc IN {hot_name}
            LET file_id = FIRST(
                FOR f IN INBOUND doc file_has_vectors
                    RETURN f._id
            )
            LET genres = (
                FOR edge IN song_has_tags
                    FILTER edge._from == file_id
                    FOR tag IN tags
                        FILTER tag._id == edge._to AND tag.rel == "genre"
                        RETURN tag.value
            )
            UPSERT {{ _key: doc._key }}
            INSERT MERGE(doc, {{ genres: genres }})
            UPDATE MERGE(doc, {{ genres: genres }})
            IN {cold_name}
        COLLECT WITH COUNT INTO n
        RETURN n
        """
    )
    results = list(cursor)  # type: ignore[arg-type]
    drained: int = results[0] if results else 0

    # Migrate file_has_vectors edges from hot → cold
    # Resolve file_id via edge traversal (file_id field dropped in migration)
    db.aql.execute(
        f"""
        FOR doc IN {cold_name}
            LET file_id = FIRST(
                FOR f IN INBOUND doc file_has_vectors
                    RETURN f._id
            )
            FILTER file_id != null
            LET hot_id = CONCAT("{hot_name}/", doc._key)
            LET cold_id = doc._id
            // Remove old edge pointing to hot (if exists)
            FOR e IN file_has_vectors
                FILTER e._to == hot_id
                REMOVE e IN file_has_vectors
            // UPSERT edge pointing to cold
            UPSERT {{ _from: file_id, _to: cold_id }}
            INSERT {{ _from: file_id, _to: cold_id }}
            UPDATE {{}}
            IN file_has_vectors
        """
    )

    # Clear hot collection now that all docs are in cold
    hot_coll.truncate()

    logger.info(
        "Drained %d documents from %s to %s",
        drained,
        hot_name,
        cold_name,
    )
    return drained


def verify_hot_empty(db: DatabaseLike, backbone_id: str, library_key: str) -> None:
    """Verify hot collection is empty after drain (completeness check).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Raises:
        RuntimeError: If hot collection is not empty.

    """
    hot_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    if not db.has_collection(hot_name):
        return  # Hot doesn't exist = empty

    hot_coll = db.collection(hot_name)
    hot_count = hot_coll.count()

    if hot_count > 0:  # type: ignore[operator]  # count() returns int in sync context
        raise RuntimeError(
            f"Hot collection '{hot_name}' not empty after drain: {hot_count} documents remain. "
            "This indicates drain operation failed or concurrent writes occurred during promotion."
        )


def drop_cold_vector_index(db: DatabaseLike, backbone_id: str, library_key: str) -> None:
    """Drop vector index from cold collection (free memory before drain).

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
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


def has_vector_index(db: DatabaseLike, backbone_id: str, library_key: str) -> bool:
    """Check if cold collection has a vector index.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        True if cold collection has vector index, False otherwise.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if not db.has_collection(cold_name):
        return False

    cold_coll = db.collection(cold_name)
    existing_indexes = cold_coll.indexes()

    return any(
        idx.get("type") == "vector"
        for idx in existing_indexes  # type: ignore[union-attr]
    )


def build_cold_vector_index(
    db: DatabaseLike,
    backbone_id: str,
    library_key: str,
    embed_dim: int,
    nlists: int,
) -> None:
    """Build vector index on cold collection.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        embed_dim: Embedding dimension (from derive_embed_dim).
        nlists: Number of HNSW graph lists (controls memory/accuracy tradeoff).

    Raises:
        ValueError: If cold collection doesn't exist.
        Exception: If index creation fails.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if not db.has_collection(cold_name):
        raise ValueError(
            f"Cold collection '{cold_name}' does not exist. Run drain_hot_to_cold first to create cold collection."
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
                "fields": ["vector_n"],
                "params": {
                    "metric": "cosine",
                    "dimension": embed_dim,
                    "nLists": nlists,
                },
                "storedValues": ["genres"],
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
        raise RuntimeError(f"Vector index creation failed on {cold_name}: {exc}") from exc


def rebuild_cold_vector_index(
    db: DatabaseLike,
    backbone_id: str,
    library_key: str,
    embed_dim: int,
    nlists: int,
) -> None:
    """Drop existing vector index and rebuild it on the cold collection.

    Combines drop + build as a single operation for use when data is already
    fully promoted and only the index parameters need updating.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        embed_dim: Embedding dimension (from derive_embed_dim).
        nlists: Number of Voronoi cells (controls recall/speed tradeoff).

    Raises:
        ValueError: If cold collection doesn't exist.
        RuntimeError: If index creation fails.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if not db.has_collection(cold_name):
        raise ValueError(
            f"Cold collection '{cold_name}' does not exist. "
            "Run promote & rebuild first to populate the cold collection."
        )

    logger.info(
        "[rebuild index] Starting for %s (dim=%d, nlists=%d)",
        cold_name,
        embed_dim,
        nlists,
    )

    # Drop existing index if present
    drop_cold_vector_index(db, backbone_id, library_key)

    # Build fresh index on the fully-populated cold collection
    build_cold_vector_index(db, backbone_id, library_key, embed_dim, nlists)

    logger.info("[rebuild index] Completed for %s", cold_name)


def backfill_genres(db: DatabaseLike, backbone_id: str, library_key: str) -> int:
    """Backfill genres on cold vector documents that predate genre enrichment.

    This is a one-time maintenance operation for cold collection documents that
    were drained before genre enrichment was added to ``drain_hot_to_cold``.
    Each document is updated in-place: a ``genres`` field is populated by joining
    via file_has_vectors edge to the file, then song_has_tags edges and tags
    documents where ``tag.rel == "genre"`` for the associated file.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier (e.g., ``"discogs_effnet"``).
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of cold documents updated with genre data.

    Raises:
        ValueError: If the cold collection does not exist.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if not db.has_collection(cold_name):
        raise ValueError(
            f"Cold collection '{cold_name}' does not exist. "
            "Run drain_hot_to_cold first to create and populate the cold collection."
        )

    cursor = db.aql.execute(
        """
        FOR doc IN @@cold_coll
            // Find associated file via edge traversal (FK-free)
            LET file_ids = (
                FOR f IN INBOUND doc file_has_vectors
                    RETURN f._id
            )
            LET file_id = FIRST(file_ids)
            FILTER file_id != null
            LET genres = (
                FOR edge IN song_has_tags
                    FILTER edge._from == file_id
                    FOR tag IN tags
                        FILTER tag._id == edge._to AND tag.rel == "genre"
                        RETURN tag.value
            )
            UPDATE doc WITH { genres: genres } IN @@cold_coll
            COLLECT WITH COUNT INTO updated
            RETURN updated
        """,
        bind_vars={"@cold_coll": cold_name},
    )

    results = list(cursor)  # type: ignore[arg-type]
    count: int = results[0] if results else 0

    logger.info(
        "Backfilled genres on %d documents in %s",
        count,
        cold_name,
    )
    return count
