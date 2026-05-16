"""Retrieve and search promoted track embeddings from cold vector collections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_cold_track_vector(
    db: Database,
    file_id: str,
    backbone_id: str,
    library_key: str,
) -> dict[str, Any] | None:
    """Fetch a track's vector document from the cold collection.

    Cold collections hold promoted, indexed vectors. Hot collections are
    write-only (accumulation during ML processing) and must never be
    searched.

    Args:
        db: Database instance.
        file_id: Library file document ``_id``.
        backbone_id: Backbone identifier (e.g. ``"effnet"``).
        library_key: ArangoDB ``_key`` of the owning library.

    Returns:
        Vector document dict (includes ``vector_n``, ``score``, etc.)
        or ``None`` if no promoted vector exists.

    """
    cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if int(db.ml.get_embedding_stats(backbone_id, library_key)["cold_count"]) <= 0:
        logger.debug(
            "Cold collection %s does not exist for backbone=%s, library=%s",
            cold_coll_name,
            backbone_id,
            library_key,
        )
        return None

    cold_ops = get_cold_namespace(db, backbone_id, library_key)
    return cold_ops.get_vector(file_id)


def search_similar_cold_track_vectors(
    db: Database,
    backbone_id: str,
    library_key: str,
    seed_vector: list[float],
    result_limit: int,
    vector_group_size: int,
    vector_search_thoroughness: int,
) -> list[dict[str, Any]]:
    """Run ANN similarity search against the promoted cold collection.

    Searches the promoted cold vector namespace for the given backbone and
    library. If the cold collection is empty, returns an empty result set and
    logs a debug message instead of issuing a search.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier used to select the cold namespace.
        library_key: ArangoDB ``_key`` of the owning library.
        seed_vector: Query embedding vector used as the ANN search seed.
        result_limit: Maximum number of similar vector documents to return.
        vector_group_size: Target group size used to derive ANN ``nlists`` from
            the collection document count.
        vector_search_thoroughness: Search thoroughness used to derive ANN
            ``nprobe`` from ``nlists``.

    Returns:
        List of matching cold vector documents. Returns an empty list when the
        promoted cold collection contains no documents.

    """
    cold_ops = get_cold_namespace(db, backbone_id, library_key)
    doc_count = int(cold_ops.count())
    if doc_count <= 0:
        logger.debug(
            "Skipping ANN search because cold collection is empty for backbone=%s, library=%s",
            backbone_id,
            library_key,
        )
        return []

    nlists = compute_nlists(doc_count, vector_group_size)
    nprobe = compute_nprobe(nlists, vector_search_thoroughness)
    return cast("list[dict[str, Any]]", cold_ops.ann_search(seed_vector, result_limit, nprobe=nprobe))
