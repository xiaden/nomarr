"""Tag cleanup component - remove orphaned tags from tags collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags(db: Database) -> int:
    """
    Remove tags that are no longer referenced by any song.

    Tags become orphaned when:
    - Songs are deleted
    - Song metadata is updated to use different tags

    Args:
        db: Database instance

    Returns:
        Count of deleted tags
    """
    return db.tags.cleanup_orphaned_tags()


def get_orphaned_tag_count(db: Database) -> int:
    """
    Count orphaned tags in the tags collection without deleting.

    Args:
        db: Database instance

    Returns:
        Count of orphaned tags
    """
    return db.tags.get_orphaned_tag_count()
