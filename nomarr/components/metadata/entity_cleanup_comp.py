"""Entity cleanup component - remove orphaned entities from entity collections."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

# Entity collections to clean
ENTITY_COLLECTIONS = ["artists", "albums", "labels", "genres", "years"]


def cleanup_orphaned_entities(db: Database) -> dict[str, int]:
    """
    Remove entities that are no longer referenced by any song.

    Entities become orphaned when:
    - Songs are deleted
    - Song metadata is updated to reference different entities

    Args:
        db: Database instance

    Returns:
        Dict mapping collection name to count of deleted entities
    """
    deleted_counts: dict[str, int] = {}

    for collection in ENTITY_COLLECTIONS:
        count = db.entities.cleanup_orphaned_entities(collection)
        deleted_counts[collection] = count

    return deleted_counts


def get_orphaned_entity_counts(db: Database) -> dict[str, int]:
    """
    Count orphaned entities in each collection without deleting.

    Args:
        db: Database instance

    Returns:
        Dict mapping collection name to count of orphaned entities
    """
    orphaned_counts: dict[str, int] = {}

    for collection in ENTITY_COLLECTIONS:
        count = db.entities.count_orphaned_entities(collection)
        orphaned_counts[collection] = count

    return orphaned_counts
