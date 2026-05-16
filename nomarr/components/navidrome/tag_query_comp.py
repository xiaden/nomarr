"""Tag query persistence wrappers for navidrome workflows.

Absorbs all intent-level `db.library.*` tag queries from navidrome workflows
so they never touch persistence directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tag_query_comp import get_file_ids_matching_tag
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
