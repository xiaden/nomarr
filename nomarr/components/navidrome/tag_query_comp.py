"""Tag query persistence wrappers for navidrome workflows.

Absorbs all db.tags.* and related calls from navidrome workflows so they
never touch persistence directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from nomarr.components.library.library_file_query_comp import get_tracks_by_file_ids
from nomarr.components.tagging.tag_query_comp import get_file_ids_matching_tag
from nomarr.components.tagging.tag_stats_comp import get_tag_value_counts as get_tag_value_counts_map
from nomarr.components.tagging.tag_stats_comp import get_unique_names
from nomarr.helpers.tag_key_mapping import is_versioned_ml_key, make_short_tag_name

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_nomarr_tag_names(db: Database) -> list[str]:
    """Get all unique tag names used by Nomarr.

    Args:
        db: Database instance

    Returns:
        List of tag names (e.g., ['nom:mood-strict', 'nom:energy'])

    """
    return get_unique_names(db, nomarr_only=True)


def get_tag_value_counts(db: Database, name: str) -> dict[Any, int]:
    """Get value distribution for a specific tag name.

    Args:
        db: Database instance
        name: Tag name (e.g., 'nom:mood-strict')

    Returns:
        Dict mapping tag values to their occurrence counts

    """
    return get_tag_value_counts_map(db, name)


def find_files_matching_tag(
    db: Database,
    name: str,
    operator: str,
    value: Any,
) -> set[str]:
    """Find file IDs matching a tag condition.

    Args:
        db: Database instance
        name: Tag name (e.g., 'nom:mood-strict')
        operator: Comparison operator ('>', '<', '>=', '<=', '=', '!=', 'CONTAINS')
        value: Value to compare against

    Returns:
        Set of file IDs matching the condition

    """
    result = get_file_ids_matching_tag(db, name=name, operator=operator, value=value)
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
    return get_tracks_by_file_ids(
        db,
        file_ids=file_ids,
        order_by=order_by,
        limit=limit,
    )


def get_short_to_versioned_mapping(
    db: Database,
    namespace: str = "nom",
) -> dict[str, list[str]]:
    """Build mapping from short names to versioned storage keys.

    Used by playlist query resolution to convert user-friendly short names
    to actual stored tag keys for database queries.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        Dict mapping short_name → list of versioned keys that share that label.
        Most short names map to exactly one versioned key, but future calibrations
        could create multiple versions of the same label.

    """
    all_names = get_nomarr_tag_names(db)
    nom_names = [name for name in all_names if name.startswith(f"{namespace}:")]

    mapping: dict[str, list[str]] = {}

    for name in nom_names:
        # Determine if numeric by checking if it's a versioned key
        is_numeric = is_versioned_ml_key(name)
        short_name = make_short_tag_name(name, is_numeric=is_numeric)

        if short_name not in mapping:
            mapping[short_name] = []
        mapping[short_name].append(name)

    return mapping


def resolve_short_to_versioned_keys(
    short_name: str,
    db: Database,
    namespace: str = "nom",
) -> list[str]:
    """Resolve a short tag name to its versioned storage key(s).

    Args:
        short_name: Short tag name (e.g., "nom-happy-raw")
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        List of versioned keys that match this short name.
        Empty list if no match found.

    """
    mapping = get_short_to_versioned_mapping(db, namespace)
    return mapping.get(short_name, [])
