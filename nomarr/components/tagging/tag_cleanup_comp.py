"""Tag cleanup helpers.

Delegates orphan-tag discovery/count and deletion to the sealed tag facade
(``db.library.count_orphaned_tags`` for the non-destructive count and
``db.library.admin_cleanup_orphaned_tags`` for the destructive cleanup returning
the typed ``TagCleanupResult``). Callers branch on ``dry_run`` at the
workflow/component boundary. No integer tag-id bookkeeping or raw edge scans
remain at this layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult
    from nomarr.persistence.db import Database


def count_orphaned_tags(db: Database) -> int:
    """Count orphaned tags (no song assignment) without deleting any.

    Non-destructive read intent used for ``dry_run=True`` previews; returns the
    number of orphaned tags while guaranteeing no deletion.
    """
    return db.library.count_orphaned_tags()


def cleanup_orphaned_tags(db: Database) -> TagCleanupResult:
    """Delete orphaned tags and return the typed domain result.

    Delegates the whole orphan discovery + deletion to the sealed destructive
    domain intent; callers never list or delete tag ids themselves. For a
    non-destructive preview, use ``count_orphaned_tags`` instead.
    """
    return db.library.admin_cleanup_orphaned_tags()
