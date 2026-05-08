"""V030: drop all named graphs and dead-weight legacy collections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.30"
DESCRIPTION: str = "Drop all named graphs and legacy dead-weight collections"

# Named graphs to drop.  ArangoDB forbids dropping a collection that belongs
# to a graph, so graphs must go first.
_GRAPHS = [
    "file_graph",
    "library_graph",
    "tag_graph",
    "ml_graph",
    "navidrome_graph",
]

# Stale collections that are no longer part of the active schema.
_COLLECTIONS = [
    "file_has_segment_stats",  # replaced by file_has_output_stream
    "segment_scores_stats",  # replaced by ml_output_streams
    "vectors_track_hot",  # replaced by vectors_track_hot__{backbone}__{lib}
    "vectors_track_cold",  # replaced by vectors_track_cold__{backbone}__{lib}
    "ml_capacity_estimates",  # migrated to meta collection (key: capacity_estimate:*)
]


def upgrade(db: DatabaseLike) -> None:
    """Drop named graphs then dead collections.

    Named graphs must be removed before their edge collections can be dropped.
    All operations are skip-if-absent so the migration is safe to re-run.
    """
    for graph_name in _GRAPHS:
        if not db.has_graph(graph_name):  # type: ignore[union-attr]
            logger.info("[V030] Skipping missing graph %s", graph_name)
            continue
        db.delete_graph(graph_name)  # type: ignore[union-attr]
        logger.info("[V030] Dropped graph %s", graph_name)

    for collection_name in _COLLECTIONS:
        if not db.has_collection(collection_name):  # type: ignore[union-attr]
            logger.info("[V030] Skipping missing collection %s", collection_name)
            continue
        db.delete_collection(collection_name)  # type: ignore[union-attr]
        logger.info("[V030] Dropped collection %s", collection_name)
