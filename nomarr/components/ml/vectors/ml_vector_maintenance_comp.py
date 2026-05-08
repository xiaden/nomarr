"""Vector store maintenance operations.

Provides primitives for hot/cold vector store promotion and index rebuilding.
Never called during bootstrap (maintenance workflow only).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.onnx.ml_discovery_comp import _resolve_embedding_graph
from nomarr.components.ml.vectors.ml_vector_registry_comp import (
    get_cold_namespace,
    get_hot_namespace,
    get_maintenance_namespace,
)
from nomarr.persistence.base_types import Field

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _load_vector_docs(vector_ops: Any) -> list[dict[str, Any]]:
    """Load all vector documents from a hot or cold namespace."""
    doc_count = cast("int", vector_ops.count())
    if doc_count <= 0:
        return []

    doc_ids = [str(row["value"]) for row in vector_ops.aggregate("_id", limit=doc_count) if "value" in row]
    if not doc_ids:
        return []

    docs = [cast("dict[str, Any] | None", vector_ops.get(_id=doc_id)) for doc_id in doc_ids]
    return [doc for doc in docs if doc is not None]


def _get_genres_for_files(db: Database, file_ids: list[str]) -> dict[str, list[str]]:
    """Resolve distinct genre tag values for a batch of files.

    Returns a mapping of file_id → list[genre_value].
    One edge query + one tag batch fetch; O(1) round trips regardless of batch size.
    """
    if not file_ids:
        return {}

    tag_edges = cast(
        "list[dict[str, Any]]",
        [
            edge
            for file_id in file_ids
            for edge in cast("list[dict[str, Any]]", db.song_has_tags.get(_from=file_id, limit=None))
        ],
    )

    tag_ids = list({edge["_to"] for edge in tag_edges if isinstance(edge.get("_to"), str)})
    if not tag_ids:
        return {fid: [] for fid in file_ids}

    tag_docs = cast("list[dict[str, Any]]", db.tags.get.in_(Field("_id", tag_ids)))
    genre_by_tag_id: dict[str, str] = {
        doc["_id"]: doc["value"]
        for doc in tag_docs
        if doc.get("name") == "genre" and isinstance(doc.get("_id"), str) and isinstance(doc.get("value"), str)
    }

    result: dict[str, list[str]] = {fid: [] for fid in file_ids}
    seen: dict[str, set[str]] = {fid: set() for fid in file_ids}
    for edge in tag_edges:
        fid = edge.get("_from")
        tag_id = edge.get("_to")
        if not isinstance(fid, str) or not isinstance(tag_id, str):
            continue
        genre = genre_by_tag_id.get(tag_id)
        if genre and genre not in seen[fid]:
            seen[fid].add(genre)
            result[fid].append(genre)

    return result


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


def drain_hot_to_cold(db: Database, backbone_id: str, library_key: str) -> int:
    """Drain all vectors from hot to cold collection (convergent UPSERT + truncate).

    Moves all documents from hot to cold, re-pointing every edge, then truncates hot.
    Safe to run multiple times (UPSERT semantics on ``_key``).

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of documents drained from hot.

    Raises:
        ValueError: If the hot collection does not exist.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    hot_ops = get_hot_namespace(db, backbone_id, library_key)
    drained = cast("int", hot_ops.move_collection(cold_name))
    db.register(cold_name, "vectors_track_cold")
    return drained


def verify_hot_empty(db: Database, backbone_id: str, library_key: str) -> None:
    """Verify hot collection is empty after drain (completeness check).

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Raises:
        RuntimeError: If hot collection is not empty.

    """
    maintenance = get_maintenance_namespace(db, backbone_id, library_key)
    hot_count = cast("int", maintenance.get_stats()["hot_count"])

    if hot_count > 0:
        raise RuntimeError(
            f"Hot collection 'vectors_track_hot__{backbone_id}__{library_key}' "
            f"not empty after drain: {hot_count} documents remain. "
            "This indicates drain operation failed or concurrent writes occurred during promotion."
        )


def drop_cold_vector_index(db: Database, backbone_id: str, library_key: str) -> None:
    """Drop vector index from cold collection (free memory before drain).

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    """
    maintenance = get_maintenance_namespace(db, backbone_id, library_key)
    try:
        maintenance.drop_index()
    except ValueError:
        return


def has_vector_index(db: Database, backbone_id: str, library_key: str) -> bool:
    """Check if cold collection has a vector index.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        True if cold collection has vector index, False otherwise.

    """
    maintenance = get_maintenance_namespace(db, backbone_id, library_key)
    return bool(maintenance.get_stats()["index_exists"])


def build_cold_vector_index(
    db: Database,
    backbone_id: str,
    library_key: str,
    embed_dim: int,
    nlists: int,
) -> None:
    """Build vector index on cold collection.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        embed_dim: Embedding dimension (from derive_embed_dim).
        nlists: Number of HNSW graph lists (controls memory/accuracy tradeoff).

    Raises:
        ValueError: If cold collection doesn't exist.
        Exception: If index creation fails.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    maintenance = get_maintenance_namespace(db, backbone_id, library_key)
    doc_count = cast("int", maintenance.get_stats()["cold_count"])

    logger.info(
        "Building vector index on %s (dim=%d, nlists=%d, docs=%d)",
        cold_name,
        embed_dim,
        nlists,
        doc_count,
    )

    try:
        maintenance.build_index(embed_dim=embed_dim, nlists=nlists)
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
    db: Database,
    backbone_id: str,
    library_key: str,
    embed_dim: int,
    nlists: int,
) -> None:
    """Drop existing vector index and rebuild it on the cold collection.

    Combines drop + build as a single operation for use when data is already
    fully promoted and only the index parameters need updating.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        embed_dim: Embedding dimension (from derive_embed_dim).
        nlists: Number of Voronoi cells (controls recall/speed tradeoff).

    Raises:
        ValueError: If cold collection doesn't exist.
        RuntimeError: If index creation fails.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    maintenance = get_maintenance_namespace(db, backbone_id, library_key)

    logger.info(
        "[rebuild index] Starting for %s (dim=%d, nlists=%d)",
        cold_name,
        embed_dim,
        nlists,
    )

    maintenance.rebuild_index(embed_dim=embed_dim, nlists=nlists)

    logger.info("[rebuild index] Completed for %s", cold_name)


def backfill_genres(db: Database, backbone_id: str, library_key: str) -> int:
    """Backfill genres on cold vector documents that predate genre enrichment.

    This is a one-time maintenance operation for cold collection documents that
    were drained before genre enrichment was added to ``drain_hot_to_cold``.
    Each document is updated in-place: a ``genres`` field is populated by joining
    via file_has_vectors edge to the file, then song_has_tags edges and tags
    documents where ``tag.name == "genre"`` for the associated file.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier (e.g., ``"discogs_effnet"``).
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of cold documents updated with genre data.

    Raises:
        ValueError: If the cold collection does not exist.

    """
    cold_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    cold_ops = get_cold_namespace(db, backbone_id, library_key)

    try:
        cold_docs = _load_vector_docs(cast("Any", cold_ops))
    except Exception as exc:
        raise ValueError(
            f"Cold collection '{cold_name}' does not exist. "
            "Run drain_hot_to_cold first to create and populate the cold collection."
        ) from exc

    file_ids = [doc["file_id"] for doc in cold_docs if isinstance(doc.get("file_id"), str)]
    genres_by_file = _get_genres_for_files(db, file_ids)

    update_docs: list[dict[str, Any]] = []
    for cold_doc in cold_docs:
        doc_key = cold_doc.get("_key")
        file_id = cold_doc.get("file_id")
        if not isinstance(doc_key, str):
            continue
        genres = genres_by_file.get(file_id, []) if isinstance(file_id, str) else []
        update_docs.append({"_key": doc_key, "genres": genres})

    if update_docs:
        cast("Any", cold_ops).update_many(update_docs)

    count = len(cold_docs)

    logger.info(
        "Backfilled genres on %d documents in %s",
        count,
        cold_name,
    )
    return count
