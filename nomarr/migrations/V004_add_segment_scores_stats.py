"""V004: Add segment_scores_stats collection.

Per-label segment-level ML statistics collection with indexes for
file_id, head_name, tagger_version, and a compound unique index.

This collection is created idempotently by ensure_schema() which runs
before migrations. This migration verifies it exists and bridges
the schema version from 3 to 4.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 3
SCHEMA_VERSION_AFTER: int = 4
DESCRIPTION: str = "Add segment_scores_stats collection for per-label segment ML statistics"


def upgrade(db: DatabaseLike) -> None:
    """Verify segment_scores_stats collection exists.

    The collection and its indexes are created by ensure_schema() which
    runs before migrations. This migration serves as the version bridge.

    Args:
        db: ArangoDB database handle.

    Raises:
        RuntimeError: If the collection was not created by ensure_schema().

    """
    if not db.has_collection("segment_scores_stats"):
        msg = (
            "segment_scores_stats collection not found. "
            "This should have been created by ensure_schema(). "
            "Check arango_bootstrap_comp.py for the collection definition."
        )
        raise RuntimeError(msg)

    logger.info(
        "Migration V004: segment_scores_stats collection verified.",
    )
