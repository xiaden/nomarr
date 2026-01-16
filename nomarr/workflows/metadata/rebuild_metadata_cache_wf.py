"""Rebuild metadata cache workflow - repair hybrid entity graph caches.

Workflow: scan all songs and rebuild embedded metadata fields from edges.
This is the canonical repair path for cache drift.
"""

import logging

from arango.database import StandardDatabase

from nomarr.components.metadata.metadata_cache_comp import rebuild_all_song_metadata_caches

logger = logging.getLogger(__name__)


def rebuild_all_metadata_caches(db: StandardDatabase, limit: int | None = None) -> dict[str, int]:
    """Rebuild metadata cache for all songs (or limited subset).

    Reads song_tag_edges for each song and writes derived embedded fields.
    This is the authoritative repair workflow for the hybrid model.

    Args:
        db: Database handle
        limit: Optional limit for testing/debugging

    Returns:
        Dict with "songs_processed" count
    """
    logger.info("Starting metadata cache rebuild (limit=%s)", limit)

    songs_processed = rebuild_all_song_metadata_caches(db, limit=limit)

    logger.info("Completed metadata cache rebuild: %d songs", songs_processed)

    return {"songs_processed": songs_processed}
