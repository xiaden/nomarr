"""Tag query persistence wrappers for navidrome workflows.

Absorbs all db.tags.* and related calls from navidrome workflows so they
never touch persistence directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_nomarr_tag_rels(db: Database) -> list[str]:
    """Get all unique tag relationship names used by Nomarr.

    Args:
        db: Database instance

    Returns:
        List of tag relationship keys (e.g., ['nom:mood-strict', 'nom:energy'])

    """
    return db.tags.get_unique_rels(nomarr_only=True)


def get_tag_value_counts(db: Database, rel: str) -> dict[Any, int]:
    """Get value distribution for a specific tag relationship.

    Args:
        db: Database instance
        rel: Tag relationship key (e.g., 'nom:mood-strict')

    Returns:
        Dict mapping tag values to their occurrence counts

    """
    return db.tags.get_tag_value_counts(rel)


def find_files_matching_tag(
    db: Database,
    rel: str,
    operator: str,
    value: Any,
) -> set[str]:
    """Find file IDs matching a tag condition.

    Args:
        db: Database instance
        rel: Tag relationship key (e.g., 'nom:mood-strict')
        operator: Comparison operator ('>', '<', '>=', '<=', '=', '!=', 'CONTAINS')
        value: Value to compare against

    Returns:
        Set of file IDs matching the condition

    """
    result = db.tags.get_file_ids_matching_tag(
        rel=rel,
        operator=operator,
        value=value,
    )
    return set(result) if not isinstance(result, set) else result


def get_playlist_preview_tracks(
    db: Database,
    file_ids: set[str],
    *,
    order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch track details for playlist preview.

    Args:
        db: Database instance
        file_ids: Set of file IDs to fetch
        order_by: Optional list of (column, direction) tuples. If None, random order.
        limit: Maximum number of tracks to return

    Returns:
        List of track dictionaries with path, title, artist, album, etc.

    """
    return db.library_files.get_tracks_by_file_ids(
        file_ids=file_ids,
        order_by=order_by,
        limit=limit,
    )
