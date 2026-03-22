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
        raise ValueError(
            f"No embedding graph found for backbone '{backbone_id}' in {models_dir}"
        )

    try:
        import onnxruntime as ort

        session = ort.InferenceSession(
            embedding_graph, providers=["CPUExecutionProvider"]
        )
        for output in session.get_outputs():
            if output.name == "embeddings":
                shape = output.shape
                if isinstance(shape, list) and len(shape) >= 2:
                    dim = shape[-1]
                    if isinstance(dim, int) and dim > 0:
                        return dim
    except Exception as exc:
        raise ValueError(
            f"Failed to probe embedding graph '{embedding_graph}'"
        ) from exc

    raise ValueError(
        f"Cannot determine embed_dim for backbone '{backbone_id}'. "
        "Ensure backbone ONNX model has output named 'embeddings' with valid shape."
    )


def drain_hot_to_cold(db: DatabaseLike, backbone_id: str, library_key: str) -> int:
    """Drain all vectors from hot to cold collection (convergent UPSERT + truncate).

    Copies all documents from hot to cold via AQL UPSERT (idempotent by _key),
    then truncates hot. Safe to run multiple times.

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
        idx.get("type") == "vector" for idx in existing_indexes  # type: ignore[union-attr]
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
                "fields": ["vector_n"],
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



# ---------------------------------------------------------------------------
# Genre-partitioned ANN indexes
# ---------------------------------------------------------------------------


def sanitize_genre_name(genre: str) -> str:
    """Normalise a genre tag value into a valid ArangoDB collection-name fragment.

    Lower-cases, replaces non-alphanumeric chars with underscores, and
    truncates to 64 characters.
    """
    import re

    sanitized = re.sub(r"[^a-z0-9]", "_", genre.lower())
    return sanitized[:64]


def _query_genre_file_groups(
    db: DatabaseLike,
    cold_collection_name: str,
) -> dict[str, list[str]]:
    """Group file IDs from *cold_collection_name* by genre tag.

    Performs an AQL join between cold vectors and ``song_has_tags`` where
    ``rel == "genre"``, then groups by genre value.

    Returns:
        Mapping of genre label → list of file IDs that belong to that genre.

    """
    query = """
    FOR doc IN @@cold
        LET genres = (
            FOR edge IN song_has_tags
                FILTER edge._from == doc.file_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.rel == "genre"
                RETURN tag.value
        )
        FOR g IN genres
            COLLECT genre = g INTO group
            RETURN {genre: genre, file_ids: group[*].doc.file_id}
    """
    cursor = db.aql.execute(  # type: ignore[union-attr]
        query,
        bind_vars={"@cold": cold_collection_name},
    )
    result: dict[str, list[str]] = {}
    for row in cursor:  # type: ignore[union-attr]
        result[row["genre"]] = row["file_ids"]
    return result


def build_genre_partitioned_indexes(
    db: DatabaseLike,
    backbone_id: str,
    library_key: str,
    embed_dim: int,
    nlists: int,
    min_genre_tracks: int = 100,
) -> int:
    """Create per-genre sub-collections with vector indexes.

    For each genre with at least *min_genre_tracks* tracks in the cold
    collection, copies the matching vectors into a genre sub-collection
    and builds an ANN vector index on it.

    Collection naming::

        vectors_track_cold__{backbone}__{lib}__genre__{sanitized}

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        embed_dim: Embedding dimension.
        nlists: Number of Voronoi cells for the vector index.
        min_genre_tracks: Minimum track count for a genre to get its own index.

    Returns:
        Number of genre sub-collections created.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if not db.has_collection(cold_name):
        logger.warning(
            "Cold collection %s does not exist — skipping genre indexes", cold_name
        )
        return 0

    genre_groups = _query_genre_file_groups(db, cold_name)
    created = 0

    for genre, file_ids in genre_groups.items():
        if len(file_ids) < min_genre_tracks:
            continue

        sanitized = sanitize_genre_name(genre)
        genre_coll_name = (
            f"vectors_track_cold__{backbone_id}__{library_key}"
            f"__genre__{sanitized}"
        )

        # Create (or truncate) the genre sub-collection
        if db.has_collection(genre_coll_name):
            db.collection(genre_coll_name).truncate()
        else:
            db.create_collection(genre_coll_name)

        # Copy matching vectors from cold into genre sub-collection
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @@cold
                FILTER doc.file_id IN @file_ids
                INSERT doc INTO @@genre
            """,
            bind_vars={
                "@cold": cold_name,
                "file_ids": file_ids,
                "@genre": genre_coll_name,
            },
        )

        # Build vector index on the genre sub-collection
        genre_coll = db.collection(genre_coll_name)
        try:
            genre_coll.add_index(  # type: ignore[attr-defined]
                {
                    "type": "vector",
                    "fields": ["vector_n"],
                    "params": {
                        "metric": "cosine",
                        "dimension": embed_dim,
                        "nLists": nlists,
                    },
                },
            )
            created += 1
            logger.info(
                "Genre index created: %s (%d tracks)",
                genre_coll_name,
                len(file_ids),
            )
        except Exception:
            logger.error(
                "Failed to create genre index on %s",
                genre_coll_name,
                exc_info=True,
            )

    logger.info(
        "Genre-partitioned indexes: %d created for %s (library=%s)",
        created,
        backbone_id,
        library_key,
    )
    return created


def drop_genre_indexes(
    db: DatabaseLike,
    backbone_id: str,
    library_key: str,
) -> int:
    """Drop all genre sub-collections for a backbone+library pair.

    Matches collections whose name starts with
    ``vectors_track_cold__{backbone}__{library_key}__genre__``.

    Args:
        db: ArangoDB database handle.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of genre sub-collections dropped.

    """
    prefix = (
        f"vectors_track_cold__{backbone_id}__{library_key}__genre__"
    )
    collections: list[dict[str, str]] = db.collections()  # type: ignore[assignment]
    dropped = 0
    for coll in collections:
        name: str = coll["name"]
        if name.startswith(prefix):
            db.delete_collection(name)  # type: ignore[union-attr]
            dropped += 1
            logger.info("Dropped genre sub-collection: %s", name)

    logger.info(
        "Genre indexes dropped: %d for %s (library=%s)",
        dropped,
        backbone_id,
        library_key,
    )
    return dropped
