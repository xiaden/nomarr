"""Tag cleanup workflow - orchestrate orphaned tag cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags, count_orphaned_tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def cleanup_orphaned_tags_workflow(db: Database, dry_run: bool = False) -> dict[str, int]:
    """Remove orphaned tags with no remaining song edges.

    Branches at the workflow boundary on ``dry_run``: a preview counts orphaned
    tags via the non-destructive ``count_orphaned_tags`` intent and performs NO
    deletion (``deleted_count=0``); a live run calls the destructive
    ``cleanup_orphaned_tags`` intent and reports its real ``TagCleanupResult``.

    Args:
        db: Database instance
        dry_run: If True, count orphaned tags but do not delete them (preview)

    Returns:
        Dict with:
        - 'orphaned_count': count of orphaned tags found
        - 'deleted_count': count of tags deleted (0 if dry_run)

    """
    logger.debug("[tag_cleanup] Starting orphaned tag cleanup workflow")

    if dry_run:
        orphaned_count = count_orphaned_tags(db)
        orphaned_log = logger.info if orphaned_count > 0 else logger.debug
        orphaned_log("[tag_cleanup] Found %d orphaned tags (dry run)", orphaned_count)
        logger.info("[tag_cleanup] Dry run - no tags deleted")
        return {
            "orphaned_count": orphaned_count,
            "deleted_count": 0,
        }

    result = cleanup_orphaned_tags(db)
    orphaned_count = result.orphaned

    orphaned_log = logger.info if orphaned_count > 0 else logger.debug
    orphaned_log("[tag_cleanup] Found %d orphaned tags", orphaned_count)

    deleted_count = result.deleted
    deleted_log = logger.info if deleted_count > 0 else logger.debug
    deleted_log("[tag_cleanup] Deleted %d orphaned tags", deleted_count)

    return {
        "orphaned_count": orphaned_count,
        "deleted_count": deleted_count,
    }
