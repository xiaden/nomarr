"""V037: Rename tags_extracted state axis to hydrated.

- Renames file_states/tags_extracted to file_states/hydrated
- Renames file_states/tags_not_extracted to file_states/not_hydrated
- Updates all file_has_state edges to point to the new vertices
- Removes the old vertices
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.37"
DESCRIPTION: str = "Rename tags_extracted state axis to hydrated"
BATCH_SIZE: int = 500


def _ensure_new_vertices(db: DatabaseLike) -> None:
    """Insert new state vertex documents if they don't already exist."""
    new_states = [
        {"_key": "hydrated"},
        {"_key": "not_hydrated"},
    ]
    for doc in new_states:
        cursor = db.aql.execute(  # type: ignore[union-attr]
            'RETURN DOCUMENT("file_states", @key)',
            bind_vars={"key": doc["_key"]},
        )
        existing = list(cursor)  # type: ignore[arg-type]
        if not existing or existing[0] is None:
            db.aql.execute(  # type: ignore[union-attr]
                "INSERT @doc INTO file_states",
                bind_vars={"doc": doc},  # type: ignore[dict-item]
            )
            logger.info("[V037] Created file_states/%s", doc["_key"])
        else:
            logger.info("[V037] file_states/%s already exists, skipping", doc["_key"])


def _repoint_edges(db: DatabaseLike, old_state: str, new_state: str) -> None:
    """Repoint all edges from old_state to new_state in batches."""
    # Get all edge keys that need repointing
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
    logger.info("[V037] Repointing %s edges from %s to %s", total, old_state, new_state)

    if total == 0:
        return

    # Repoint in batches
    repointed = 0
    for start in range(0, total, BATCH_SIZE):
        batch = edge_keys[start : start + BATCH_SIZE]
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR key IN @edge_keys
                UPDATE { _key: key, _to: @new_state } IN file_has_state
            """,
            bind_vars={"edge_keys": batch, "new_state": new_state},
        )
        repointed += len(batch)
        logger.info("[V037] Repointed batch %s-%s (%s total)", start, start + len(batch), repointed)

    logger.info("[V037] Repointed %s edges total from %s to %s", repointed, old_state, new_state)


def _remove_old_vertices(db: DatabaseLike) -> None:
    """Remove the old tags_extracted and tags_not_extracted state vertex documents."""
    for key in ("tags_extracted", "tags_not_extracted"):
        cursor = db.aql.execute(  # type: ignore[union-attr]
            'RETURN DOCUMENT("file_states", @key)',
            bind_vars={"key": key},
        )
        if next(iter(cursor), None) is not None:  # type: ignore[arg-type]
            db.aql.execute(  # type: ignore[union-attr]
                "REMOVE @key IN file_states",
                bind_vars={"key": key},
            )
            logger.info("[V037] Removed file_states/%s vertex", key)
        else:
            logger.info("[V037] file_states/%s already absent, skipping", key)


def upgrade(db: DatabaseLike) -> None:
    """Rename tags_extracted axis to hydrated."""
    logger.info("[V037] Ensuring hydrated and not_hydrated state vertices")
    _ensure_new_vertices(db)

    logger.info("[V037] Repointing edges from tags_extracted to hydrated")
    _repoint_edges(db, "file_states/tags_extracted", "file_states/hydrated")

    logger.info("[V037] Repointing edges from tags_not_extracted to not_hydrated")
    _repoint_edges(db, "file_states/tags_not_extracted", "file_states/not_hydrated")

    logger.info("[V037] Removing old vertices")
    _remove_old_vertices(db)

    logger.info("[V037] Migration complete")
