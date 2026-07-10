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
) -> dict[str, Any] | None:
    """Fetch a track's vector document from the cold collection.

    Cold collections hold promoted, indexed vectors.  Hot collections are
    write-only (accumulation during ML processing) and must never be
    searched.

    Uses per-backbone cold collections (cross-library).

    Args:
        db: Database instance.
        file_id: Library file document ``_id``.
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        Vector document dict (includes ``vector_n``, ``score``, etc.)
        or ``None`` if no promoted vector exists.

    """
    stats = db.ml.get_embedding_stats(backbone_id)
    cold_count = stats.get("cold_count", 0)
    if cold_count is None or int(cold_count) <= 0:
        logger.debug(
            "[vectors] Cold collection is empty for backbone=%s",
            backbone_id,
        )
        return None

    cold_ops = get_cold_namespace(db, backbone_id)
    return cold_ops.get_vector(file_id)


def search_similar_cold_track_vectors(
    db: Database,
    backbone_id: str,
    seed_vector: list[float],
    result_limit: int,
    vector_group_size: int,
    vector_search_thoroughness: int,
) -> list[dict[str, Any]]:
    """Run ANN similarity search against the promoted cold collection.

    Searches the per-backbone cold vector namespace.  If the cold collection
    is empty, returns an empty result set and logs a debug message instead
    of issuing a search.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier used to select the cold namespace.
        seed_vector: Query embedding vector used as the ANN search seed.
        result_limit: Maximum number of similar vector documents to return.
        vector_group_size: Target group size used to derive ANN ``nlists``
            from the collection document count.
        vector_search_thoroughness: Search thoroughness used to derive ANN
            ``nprobe`` from ``nlists``.

    Returns:
        List of matching cold vector documents.  Returns an empty list when
        the promoted cold collection contains no documents.

    """
    cold_ops = get_cold_namespace(db, backbone_id)
    doc_count = cold_ops.count()
    if doc_count <= 0:
        logger.debug(
            "Skipping ANN search because cold collection is empty for backbone=%s",
            backbone_id,
        )
        return []

    nlists = compute_nlists(doc_count, vector_group_size)
    nprobe = compute_nprobe(nlists, vector_search_thoroughness)
    return cast("list[dict[str, Any]]", cold_ops.ann_search(seed_vector, result_limit, nprobe=nprobe))
