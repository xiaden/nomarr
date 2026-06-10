"""V036: Rename file states for clarity.

This migration renames file state vertices to better reflect their meaning:

- file_states/tagged → file_states/processed (ML inference completed)
- file_states/not_tagged → file_states/not_processed (ML inference not yet run)
- file_states/tags_written → file_states/written (tags written to audio file)
- file_states/tags_not_written → file_states/not_written (tags not yet written)

For each rename:
- Creates new vertex if it doesn't exist
- Updates all file_has_state edges from old to new
- Removes the old vertex
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.36"
DESCRIPTION: str = "Rename file states for clarity (tagged→processed, tags_written→written)"
BATCH_SIZE: int = 500

# State renames: (old_key, new_key)
_STATE_RENAMES = [
    ("tagged", "processed"),
    ("not_tagged", "not_processed"),
    ("tags_written", "written"),
    ("tags_not_written", "not_written"),
]


def _ensure_new_vertex(db: DatabaseLike, vertex_key: str) -> None:
    """Create a vertex if it doesn't already exist."""
    cursor = db.aql.execute(  # type: ignore[union-attr]
        'RETURN DOCUMENT("file_states", @key)',
        bind_vars={"key": vertex_key},
    )
    existing = list(cursor)  # type: ignore[arg-type]
    if not existing or existing[0] is None:
        db.aql.execute(  # type: ignore[union-attr]
            "INSERT @doc INTO file_states",
            bind_vars={"doc": {"_key": vertex_key}},
        )
        logger.info("[V036] Created file_states/%s", vertex_key)
    else:
        logger.info("[V036] file_states/%s already exists, skipping", vertex_key)


def _migrate_edges(db: DatabaseLike, old_key: str, new_key: str) -> None:
    """Update all edges from old state to new state in batches."""
    old_state = f"file_states/{old_key}"
    new_state = f"file_states/{new_key}"

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
    logger.info("[V036] Found %s edges to migrate from %s to %s", total, old_key, new_key)

    if total == 0:
        return

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
        logger.info("[V036] Migrated batch %s-%s (%s total)", start, start + len(batch), migrated)

    logger.info("[V036] Migrated %s edges total from %s to %s", migrated, old_key, new_key)


def _remove_old_vertex(db: DatabaseLike, vertex_key: str) -> None:
    """Remove the old vertex document."""
    cursor = db.aql.execute(  # type: ignore[union-attr]
        'RETURN DOCUMENT("file_states", @key)',
        bind_vars={"key": vertex_key},
    )
    if next(iter(cursor), None) is not None:  # type: ignore[arg-type]
        db.aql.execute(  # type: ignore[union-attr]
            "REMOVE @key IN file_states",
            bind_vars={"key": vertex_key},
        )
        logger.info("[V036] Removed file_states/%s vertex", vertex_key)
    else:
        logger.info("[V036] file_states/%s already absent, skipping", vertex_key)


def upgrade(db: DatabaseLike) -> None:
    """Rename file states for clarity."""
    for old_key, new_key in _STATE_RENAMES:
        logger.info("[V036] Renaming %s to %s", old_key, new_key)

        logger.info("[V036] Ensuring %s vertex exists", new_key)
        _ensure_new_vertex(db, new_key)

        logger.info("[V036] Migrating edges from %s to %s", old_key, new_key)
        _migrate_edges(db, old_key, new_key)

        logger.info("[V036] Removing old %s vertex", old_key)
        _remove_old_vertex(db, old_key)

    logger.info("[V036] Migration complete")
