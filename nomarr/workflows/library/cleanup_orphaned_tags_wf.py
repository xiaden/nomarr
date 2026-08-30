"""Tag cleanup workflow - orchestrate orphaned tag cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def cleanup_orphaned_tags_workflow(db: Database, dry_run: bool = False) -> dict[str, int]:
    """Remove orphaned tags with no remaining song edges.

    Calls the single domain orphan-cleanup intent and consumes its typed
    result. ``dry_run`` suppresses the reported deletion count; the sealed
    intent performs orphan discovery atomically (there is no count-only facade
    method), so the orphaned count is always the intent's discovered count.

    Args:
        db: Database instance
        dry_run: If True, report deleted_count as 0 (preview)

    Returns:
        Dict with:
        - 'orphaned_count': count of orphaned tags found
        - 'deleted_count': count of tags deleted (0 if dry_run)

    """
    logger.debug("[tag_cleanup] Starting orphaned tag cleanup workflow")

    result = cleanup_orphaned_tags(db)
    orphaned_count = result.orphaned

    orphaned_log = logger.info if orphaned_count > 0 else logger.debug
    orphaned_log("[tag_cleanup] Found %d orphaned tags", orphaned_count)

    if dry_run:
        logger.info("[tag_cleanup] Dry run - no tags deleted")
        return {
            "orphaned_count": orphaned_count,
            "deleted_count": 0,
        }

    deleted_count = result.deleted
    deleted_log = logger.info if deleted_count > 0 else logger.debug
    deleted_log("[tag_cleanup] Deleted %d orphaned tags", deleted_count)

    return {
        "orphaned_count": orphaned_count,
        "deleted_count": deleted_count,
    }
