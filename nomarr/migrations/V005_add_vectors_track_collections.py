"""V005: Add per-backbone vectors_track collections.

Collection-per-backbone architecture for storing pooled backbone
embeddings as track-level vectors. Each collection is named
``vectors_track__{backbone}`` (e.g., ``vectors_track__effnet``).

Collections are created idempotently by ensure_schema() which runs
before migrations. This migration verifies at least one exists and
bridges the schema version from 4 to 5.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 4
SCHEMA_VERSION_AFTER: int = 5
DESCRIPTION: str = "Add per-backbone vectors_track collections for embedding persistence"

_VECTORS_TRACK_PREFIX = "vectors_track__"


def upgrade(db: DatabaseLike) -> None:
    """Verify vectors_track collections exist.

    The collections are created by ensure_schema() when models_dir is
    provided. This migration verifies at least one exists. If no
    backbones are discovered (models_dir not provided or empty), the
    collections may not exist yet — that is acceptable since they will
    be created on next startup with models available.

    Args:
        db: ArangoDB database handle.

    """
    collections = db.collections()  # type: ignore[union-attr]
    if collections is None:
        logger.warning(
            "Migration V005: Could not list collections. "
            "vectors_track collections will be created on next startup.",
        )
        return

    vt_collections = [
        c["name"]
        for c in collections  # type: ignore[union-attr]
        if c["name"].startswith(_VECTORS_TRACK_PREFIX)
    ]

    if vt_collections:
        logger.info(
            "Migration V005: Found %d vectors_track collection(s): %s",
            len(vt_collections),
            ", ".join(sorted(vt_collections)),
        )
    else:
        logger.info(
            "Migration V005: No vectors_track collections found yet. "
            "They will be created on next startup when models are available.",
        )
