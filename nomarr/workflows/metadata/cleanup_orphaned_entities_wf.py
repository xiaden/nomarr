"""Tag cleanup workflow - orchestrate orphaned tag cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.metadata.entity_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def cleanup_orphaned_entities_workflow(db: Database, dry_run: bool = False) -> dict[str, int | dict[str, int]]:
    """Clean up orphaned tags from the tags collection.

    Removes tags that have no incoming edges from songs. This happens when
    songs are deleted or metadata is updated.

    Note: Function name kept for API compatibility, but now cleans tags.

    Args:
        db: Database instance
        dry_run: If True, count orphaned tags but don't delete them

    Returns:
        Dict with:
        - 'orphaned_counts': Dict with 'tags' -> count of orphaned tags found
        - 'deleted_counts': Dict with 'tags' -> count of tags deleted (0 if dry_run)
        - 'total_orphaned': Total orphaned tags
        - 'total_deleted': Total deleted tags (0 if dry_run)

    """
    logger.info("[tag_cleanup] Starting orphaned tag cleanup workflow")

    # Count orphaned tags
    orphaned_count = get_orphaned_tag_count(db)

    logger.info(f"[tag_cleanup] Found {orphaned_count} orphaned tags")

    orphaned_counts = {"tags": orphaned_count}

    if dry_run:
        logger.info("[tag_cleanup] Dry run - no tags deleted")
        return {
            "orphaned_counts": orphaned_counts,
            "deleted_counts": {"tags": 0},
            "total_orphaned": orphaned_count,
            "total_deleted": 0,
        }

    # Delete orphaned tags
    deleted_count = cleanup_orphaned_tags(db)

    logger.info(f"[tag_cleanup] Deleted {deleted_count} orphaned tags")

    return {
        "orphaned_counts": orphaned_counts,
        "deleted_counts": {"tags": deleted_count},
        "total_orphaned": orphaned_count,
        "total_deleted": deleted_count,
    }
