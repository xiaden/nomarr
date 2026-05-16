"""Tag cleanup helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _get_orphaned_tag_ids(db: Database) -> list[str]:
    """Return IDs of tag documents that have no song_has_tags edges."""
    return db.library.maintenance.list_orphaned_tag_ids()


def cleanup_orphaned_tags(db: Database) -> int:
    """Delete tag documents that have no song_has_tags edges."""
    orphan_ids = _get_orphaned_tag_ids(db)
    if not orphan_ids:
        return 0
    return db.library.maintenance.delete_tags_by_ids(orphan_ids)


def get_orphaned_tag_count(db: Database) -> int:
    """Count tags that currently have no song_has_tags edges."""
    return len(_get_orphaned_tag_ids(db))
