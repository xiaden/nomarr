"""Tag cleanup workflow - orchestrate orphaned tag cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags_workflow(db: Database, dry_run: bool = False) -> dict[str, int]:
    """Clean up orphaned tags from the database.

    Args:
        db: Database instance
        dry_run: If True, count orphaned tags but don't delete them

    Returns:
        Dict with 'orphaned_count' and 'deleted_count' keys

    """
    logging.info("[tag_cleanup] Starting orphaned tag cleanup workflow")

    # Count orphaned tags
    orphaned_count = get_orphaned_tag_count(db)
    logging.info(f"[tag_cleanup] Found {orphaned_count} orphaned tags")

    if dry_run:
        logging.info("[tag_cleanup] Dry run - no tags deleted")
        return {"orphaned_count": orphaned_count, "deleted_count": 0}

    # Delete orphaned tags
    deleted_count = cleanup_orphaned_tags(db)
    logging.info(f"[tag_cleanup] Deleted {deleted_count} orphaned tags")

    return {"orphaned_count": orphaned_count, "deleted_count": deleted_count}
