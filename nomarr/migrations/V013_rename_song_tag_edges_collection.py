"""V013: Rename edge collection song_tag_edges to song_has_tags.

Background
----------
The ``song_tag_edges`` edge collection stores relationships between
``library_files/*`` vertices (songs) and ``tags/*`` vertices.  The old name
used a generic ``{noun}_{noun}_edges`` pattern.  The new name,
``song_has_tags``, adopts the ``{subject}_has_{object}`` convention that
clearly expresses the semantic relationship and is consistent with the rest of
the graph schema.

Forward-only; no downgrade path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 12
SCHEMA_VERSION_AFTER: int = 13
DESCRIPTION: str = "Rename edge collection song_tag_edges to song_has_tags"

_OLD_NAME = "song_tag_edges"
_NEW_NAME = "song_has_tags"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Rename the song_tag_edges edge collection to song_has_tags.

    Idempotent: if ``song_has_tags`` already exists and ``song_tag_edges``
    does not, the migration logs a no-op and returns.  This handles the case
    where the migration is re-run after a partial failure.

    Args:
        db: ArangoDB database handle.

    """
    has_old = db.has_collection(_OLD_NAME)  # type: ignore[union-attr]
    has_new = db.has_collection(_NEW_NAME)  # type: ignore[union-attr]

    if not has_old and has_new:
        logger.info(
            "Migration V013: %s already exists and %s is absent — nothing to do",
            _NEW_NAME,
            _OLD_NAME,
        )
        return

    if not has_old and not has_new:
        logger.warning(
            "Migration V013: Neither %s nor %s found — skipping",
            _OLD_NAME,
            _NEW_NAME,
        )
        return

    if has_old and has_new:
        # ensure_schema created song_has_tags (empty) before migrations ran.
        # Drop the empty shell so the rename can proceed.
        db.delete_collection(_NEW_NAME)  # type: ignore[union-attr]
        logger.info(
            "Migration V013: Dropped empty %s shell created by ensure_schema",
            _NEW_NAME,
        )

    db.collection(_OLD_NAME).rename(_NEW_NAME)  # type: ignore[union-attr]
    logger.info(
        "Migration V013: Renamed collection %s → %s", _OLD_NAME, _NEW_NAME
    )
