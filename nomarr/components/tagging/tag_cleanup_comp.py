"""Tag cleanup helpers.

Delegates orphan-tag cleanup to the sealed tag facade
(``db.library.cleanup_orphaned_tags``) and returns the typed ``TagCleanupResult``
(deleted/orphaned counts). No integer tag-id bookkeeping or raw edge scans
remain at this layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult
    from nomarr.persistence.db import Database


def cleanup_orphaned_tags(db: Database) -> TagCleanupResult:
    """Delete orphaned tags and return the typed domain result.

    Delegates the whole orphan discovery + deletion to the sealed domain
    intent; callers never list or delete tag ids themselves.
    """
    return db.library.cleanup_orphaned_tags()
