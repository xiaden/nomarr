"""V035: Rename tags_stale state vertex to tags_not_fresh.

This migration renames the file_states/tags_stale vertex to file_states/tags_not_fresh
to follow the consistent not_* naming convention for negative state poles.

- Creates file_states/tags_not_fresh vertex if it doesn't exist
- Updates all file_has_state edges from tags_stale to tags_not_fresh
- Removes the old file_states/tags_stale vertex
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.35"
DESCRIPTION: str = "Rename tags_stale state vertex to tags_not_fresh for consistent naming"
BATCH_SIZE: int = 500


def _ensure_new_vertex(db: DatabaseLike) -> None:
    """Create the tags_not_fresh vertex if it doesn't already exist."""
    cursor = db.aql.execute(  # type: ignore[union-attr]
        'RETURN DOCUMENT("file_states", "tags_not_fresh")',
    )
    existing = list(cursor)  # type: ignore[arg-type]
    if not existing or existing[0] is None:
        db.aql.execute(  # type: ignore[union-attr]
            "INSERT @doc INTO file_states",
            bind_vars={"doc": {"_key": "tags_not_fresh"}},
        )
        logger.info("[V035] Created file_states/tags_not_fresh")
    else:
        logger.info("[V035] file_states/tags_not_fresh already exists, skipping")


def _migrate_edges(db: DatabaseLike) -> None:
    """Update all edges from tags_stale to tags_not_fresh in batches."""
    old_state = "file_states/tags_stale"
    new_state = "file_states/tags_not_fresh"

    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR edge IN file_has_state
            FILTER edge._to == @old_state
            RETURN edge._key
        """,
        bind_vars={"old_state": old_state},
    )
    edge_keys = list(cursor)  # type: ignore[arg-type]
    total = len(edge_keys)
    logger.info("[V035] Found %s edges to migrate from tags_stale to tags_not_fresh", total)

    migrated = 0
    for start in range(0, total, BATCH_SIZE):
        batch = edge_keys[start : start + BATCH_SIZE]
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge_key IN @edge_keys
                UPDATE edge_key WITH { _to: @new_state } IN file_has_state
            """,
            bind_vars={"edge_keys": batch, "new_state": new_state},
        )
        migrated += len(batch)
        logger.info("[V035] Migrated batch %s-%s (%s total)", start, start + len(batch), migrated)

    logger.info("[V035] Migrated %s edges total", migrated)


def _remove_old_vertex(db: DatabaseLike) -> None:
    """Remove the old tags_stale vertex document."""
    cursor = db.aql.execute(  # type: ignore[union-attr]
        'RETURN DOCUMENT("file_states", "tags_stale")',
    )
    if next(iter(cursor), None) is not None:  # type: ignore[arg-type]
        db.aql.execute(  # type: ignore[union-attr]
            "REMOVE @key IN file_states",
            bind_vars={"key": "tags_stale"},
        )
        logger.info("[V035] Removed file_states/tags_stale vertex")
    else:
        logger.info("[V035] file_states/tags_stale already absent, skipping")


def upgrade(db: DatabaseLike) -> None:
    """Rename tags_stale to tags_not_fresh."""
    logger.info("[V035] Ensuring tags_not_fresh vertex exists")
    _ensure_new_vertex(db)

    logger.info("[V035] Migrating edges from tags_stale to tags_not_fresh")
    _migrate_edges(db)

    logger.info("[V035] Removing old tags_stale vertex")
    _remove_old_vertex(db)

    logger.info("[V035] Migration complete")
