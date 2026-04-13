"""Tag cleanup component - remove orphaned tags from tags collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags as cleanup_orphaned_tags_docs
from nomarr.components.tagging.tag_cleanup_comp import get_orphaned_tag_count as get_orphaned_tag_count_docs

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags(db: Database) -> int:
    """Remove tags that are no longer referenced by any song.

    This should be run periodically or after bulk delete operations to reclaim space.

    Args:
        db: Database instance

    Returns:
        Number of orphaned tags deleted

    """
    return cleanup_orphaned_tags_docs(db)


def get_orphaned_tag_count(db: Database) -> int:
    """Count tags that are not referenced by any song.

    Args:
        db: Database instance

    Returns:
        Number of orphaned tags

    """
    return get_orphaned_tag_count_docs(db)
