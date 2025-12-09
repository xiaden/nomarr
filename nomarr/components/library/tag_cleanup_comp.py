"""Tag cleanup component - remove orphaned tags from library_tags table."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags(db: Database) -> int:
    """
    Remove tags from library_tags that are no longer referenced by any file.

    This should be run periodically or after bulk delete operations to reclaim space.

    Args:
        db: Database instance

    Returns:
        Number of orphaned tags deleted
    """
    return db.library_tags.cleanup_orphaned_tags()


def get_orphaned_tag_count(db: Database) -> int:
    """
    Count tags in library_tags that are not referenced by any file.

    Args:
        db: Database instance

    Returns:
        Number of orphaned tags
    """
    return db.library_tags.get_orphaned_tag_count()
