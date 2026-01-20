"""Entity cleanup workflow - orchestrate orphaned entity cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.metadata.entity_cleanup_comp import cleanup_orphaned_entities, get_orphaned_entity_counts

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def cleanup_orphaned_entities_workflow(db: Database, dry_run: bool = False) -> dict[str, int | dict[str, int]]:
    """
    Clean up orphaned entities from entity collections.

    Removes entities (artists, albums, genres, labels, years) that have no
    incoming edges from songs. This happens when songs are deleted or metadata
    is updated.

    Args:
        db: Database instance
        dry_run: If True, count orphaned entities but don't delete them

    Returns:
        Dict with:
        - 'orphaned_counts': Dict[collection -> count] of orphaned entities found
        - 'deleted_counts': Dict[collection -> count] of entities deleted (0 if dry_run)
        - 'total_orphaned': Total orphaned entities across all collections
        - 'total_deleted': Total deleted entities (0 if dry_run)
    """
    logger.info("[entity_cleanup] Starting orphaned entity cleanup workflow")

    # Count orphaned entities
    orphaned_counts = get_orphaned_entity_counts(db)
    total_orphaned = sum(orphaned_counts.values())

    logger.info(
        f"[entity_cleanup] Found {total_orphaned} orphaned entities: " + ", ".join(f"{k}={v}" for k, v in orphaned_counts.items())
    )

    if dry_run:
        logger.info("[entity_cleanup] Dry run - no entities deleted")
        return {
            "orphaned_counts": orphaned_counts,
            "deleted_counts": dict.fromkeys(orphaned_counts, 0),
            "total_orphaned": total_orphaned,
            "total_deleted": 0,
        }

    # Delete orphaned entities
    deleted_counts = cleanup_orphaned_entities(db)
    total_deleted = sum(deleted_counts.values())

    logger.info(f"[entity_cleanup] Deleted {total_deleted} orphaned entities: " + ", ".join(f"{k}={v}" for k, v in deleted_counts.items()))

    return {
        "orphaned_counts": orphaned_counts,
        "deleted_counts": deleted_counts,
        "total_orphaned": total_orphaned,
        "total_deleted": total_deleted,
    }
