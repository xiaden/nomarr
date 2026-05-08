"""V030: drop legacy segment score stats collections after raw-stream cutover."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.3.0"
DESCRIPTION: str = "Drop legacy segment score stats collections"


def upgrade(db: DatabaseLike) -> None:
    """Drop the legacy segment-stats collections after canonical stream cutover.

    The canonical ML artifact is now ``ml_output_streams`` plus its file/output
    edge graph. No attempt is made to backfill raw streams from legacy summary
    stats because that information is lossy by definition.
    """
    for collection_name in ("file_has_segment_stats", "segment_scores_stats"):
        if not db.has_collection(collection_name):  # type: ignore[union-attr]
            logger.info("[V030] Skipping missing collection %s", collection_name)
            continue

        db.delete_collection(collection_name)  # type: ignore[union-attr]
        logger.info("[V030] Dropped collection %s", collection_name)
