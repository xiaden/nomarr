"""Tag cleanup workflow - orchestrate orphaned tag cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def cleanup_orphaned_entities_workflow(db: Database, dry_run: bool = False) -> dict[str, int | dict[str, int]]:
    """Clean up orphaned tags from the tags table.

    Removes tags that have no incoming edges from songs. This happens when
    songs are deleted or metadata is updated.

    Note: Function name kept for API compatibility, but now cleans tags.

    Args:
        db: Database instance
        dry_run: If True, report deleted counts as 0 (preview)

    Returns:
        Dict with:
        - 'orphaned_counts': Dict with 'tags' -> count of orphaned tags found
        - 'deleted_counts': Dict with 'tags' -> count of tags deleted (0 if dry_run)
        - 'total_orphaned': Total orphaned tags
        - 'total_deleted': Total deleted tags (0 if dry_run)

    """
    logger.debug("[tag_cleanup] Starting orphaned tag cleanup workflow")

    result = cleanup_orphaned_tags(db)
    orphaned_count = result.orphaned
    deleted_count = 0 if dry_run else result.deleted

    orphaned_log = logger.info if orphaned_count > 0 else logger.debug
    orphaned_log("[tag_cleanup] Found %d orphaned tags", orphaned_count)

    orphaned_counts = {"tags": orphaned_count}

    if dry_run:
        logger.info("[tag_cleanup] Dry run - no tags deleted")

    deleted_log = logger.info if deleted_count > 0 else logger.debug
    deleted_log("[tag_cleanup] Deleted %d orphaned tags", deleted_count)

    return {
        "orphaned_counts": orphaned_counts,
        "deleted_counts": {"tags": deleted_count},
        "total_orphaned": orphaned_count,
        "total_deleted": deleted_count,
    }
