"""Tag cleanup component - remove orphaned tags from tags collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags as cleanup_orphaned_tags_docs
from nomarr.components.tagging.tag_cleanup_comp import get_orphaned_tag_count as get_orphaned_tag_count_docs

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags(db: Database) -> int:
    """Remove tags that are no longer referenced by any song.

    Tags become orphaned when:
    - Songs are deleted
    - Song metadata is updated to use different tags

    Args:
        db: Database instance

    Returns:
        Count of deleted tags

    """
    return cleanup_orphaned_tags_docs(db)


def get_orphaned_tag_count(db: Database) -> int:
    """Count orphaned tags in the tags collection without deleting.

    Args:
        db: Database instance

    Returns:
        Count of orphaned tags

    """
    return get_orphaned_tag_count_docs(db)
