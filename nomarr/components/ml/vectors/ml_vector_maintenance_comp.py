"""Vector store maintenance operations.

Provides utilities for embedding dimension inference and cold vector data maintenance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.onnx.ml_discovery_comp import _resolve_embedding_graph
from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.persistence.schema_types import Field

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

    docs_by_id = {
        str(doc_id): doc
        for doc in cast("list[dict[str, Any]]", vector_ops.get.in_(Field("_id", doc_ids), limit=None))
        if isinstance((doc_id := doc.get("_id")), str)
    }
    return [docs_by_id[doc_id] for doc_id in doc_ids if doc_id in docs_by_id]


def _get_genres_for_files(db: Database, file_ids: list[str]) -> dict[str, list[str]]:
    """Resolve distinct genre tag values for a batch of files.

    Returns a mapping of file_id → list[genre_value].
    One edge query + one tag batch fetch; O(1) round trips regardless of batch size.
    """
    if not file_ids:
        return {}

    result: dict[str, list[str]] = {fid: [] for fid in file_ids}
    seen: dict[str, set[str]] = {fid: set() for fid in file_ids}
    genre_rows = cast("list[dict[str, Any]]", db.library.list_genre_tags_for_files(file_ids))
    for row in genre_rows:
        fid = row.get("fid")
        genre = row.get("genre")
        if not isinstance(fid, str) or fid not in seen or not isinstance(genre, str) or not genre:
            continue
        if genre not in seen[fid]:
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
