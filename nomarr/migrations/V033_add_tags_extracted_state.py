"""V033: Add tags_extracted state axis, remove too_short axis.

- Adds file_states/tags_not_extracted and file_states/tags_extracted vertices
- Removes all too_short / not_too_short edges and vertices
- Seeds tags_not_extracted edges for all files that are in the scanned state
  (so the new tag extraction worker has a full queue on startup)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.33"
DESCRIPTION: str = "Add tags_extracted state axis for background tag extraction worker; remove too_short axis"
BATCH_SIZE: int = 500


def _ensure_state_vertices(db: DatabaseLike) -> None:
    """Insert new state vertex documents if they don't already exist."""
    new_states = [
        {"_key": "tags_not_extracted"},
        {"_key": "tags_extracted"},
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
            logger.info("[V033] Created file_states/%s", doc["_key"])
        else:
            logger.info("[V033] file_states/%s already exists, skipping", doc["_key"])


def _remove_too_short_edges(db: DatabaseLike) -> None:
    """Remove all file_has_state edges pointing to too_short or not_too_short."""
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR edge IN file_has_state
            FILTER edge._to IN ["file_states/too_short", "file_states/not_too_short"]
            REMOVE edge IN file_has_state
            COLLECT WITH COUNT INTO removed
            RETURN removed
        """
    )
    count = next(iter(cursor), 0)  # type: ignore[arg-type]
    logger.info("[V033] Removed %s too_short/not_too_short state edges", count)


def _remove_too_short_vertices(db: DatabaseLike) -> None:
    """Remove the too_short and not_too_short state vertex documents."""
    for key in ("too_short", "not_too_short"):
        cursor = db.aql.execute(  # type: ignore[union-attr]
            'RETURN DOCUMENT("file_states", @key)',
            bind_vars={"key": key},
        )
        if next(iter(cursor), None) is not None:  # type: ignore[arg-type]
            db.aql.execute(  # type: ignore[union-attr]
                "REMOVE @key IN file_states",
                bind_vars={"key": key},
            )
            logger.info("[V033] Removed file_states/%s vertex", key)
        else:
            logger.info("[V033] file_states/%s already absent, skipping", key)


def _seed_tags_not_extracted(db: DatabaseLike) -> None:
    """Seed tags_not_extracted edges for all scanned files that don't have tags_extracted.

    Files already in tags_extracted keep that state. All others get tags_not_extracted.
    """
    # Find all file IDs from scanned files
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR edge IN file_has_state
            FILTER edge._to == "file_states/scanned"
            RETURN edge._from
        """
    )
    scanned_file_ids = list(cursor)  # type: ignore[arg-type]
    logger.info("[V033] Found %s scanned files to seed tags_not_extracted for", len(scanned_file_ids))

    # Get files that already have tags_extracted
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR edge IN file_has_state
            FILTER edge._to == "file_states/tags_extracted"
            RETURN edge._from
        """
    )
    already_extracted = set(cursor)  # type: ignore[arg-type]

    # Files needing tags_not_extracted = scanned - already_extracted
    pending_ids = [fid for fid in scanned_file_ids if fid not in already_extracted]
    logger.info("[V033] Seeding tags_not_extracted for %s files", len(pending_ids))

    total_seeded = 0
    for start in range(0, len(pending_ids), BATCH_SIZE):
        batch = pending_ids[start : start + BATCH_SIZE]
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR file_id IN @file_ids
                UPSERT { _from: file_id, _to: "file_states/tags_not_extracted" }
                    INSERT { _from: file_id, _to: "file_states/tags_not_extracted" }
                    UPDATE {}
                    IN file_has_state
            """,
            bind_vars={"file_ids": batch},
        )
        total_seeded += len(batch)
        logger.info("[V033] Seeded batch %s-%s (%s total)", start, start + len(batch) - 1, total_seeded)

    logger.info("[V033] Seeded tags_not_extracted for %s files total", total_seeded)


def upgrade(db: DatabaseLike) -> None:
    """Add tags_extracted axis, remove too_short axis, seed pending queue."""
    logger.info("[V033] Ensuring tags_not_extracted and tags_extracted state vertices")
    _ensure_state_vertices(db)

    logger.info("[V033] Removing too_short/not_too_short state edges")
    _remove_too_short_edges(db)

    logger.info("[V033] Removing too_short/not_too_short state vertices")
    _remove_too_short_vertices(db)

    logger.info("[V033] Seeding tags_not_extracted edges for scanned files")
    _seed_tags_not_extracted(db)

    logger.info("[V033] Migration complete")
