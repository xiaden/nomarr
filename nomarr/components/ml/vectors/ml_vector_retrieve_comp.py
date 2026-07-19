"""Retrieve and search promoted track embeddings from cold vector collections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_cold_track_vector(
    db: Database,
    file_id: int,
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

    results = db.ml.list_file_vectors(backbone_id, file_id)
    if results:
        return results[0]  # type: ignore[return-value]
    return None


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
        vector_group_size: Target group size (accepted for API compatibility;
            no longer used to derive ANN parameters — PostgreSQL manages
            the HNSW index automatically).
        vector_search_thoroughness: Search thoroughness (accepted for API
            compatibility; no longer used — PostgreSQL manages the HNSW
            index automatically).

    Returns:
        List of matching cold vector documents.  Returns an empty list when
        the promoted cold collection contains no documents.

    """
    stats = db.ml.get_embedding_stats(backbone_id)
    if stats.get("cold_count", 0) <= 0:
        logger.debug(
            "Skipping ANN search because cold collection is empty for backbone=%s",
            backbone_id,
        )
        return []

    return db.ml.search_vectors(  # type: ignore[return-value]
        backbone_id,
        seed_vector,
        limit=result_limit,
    )
