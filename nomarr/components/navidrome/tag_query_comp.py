"""Tag query persistence wrappers for Navidrome workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tag_query_comp import get_file_ids_matching_tag
from nomarr.components.tagging.tag_stats_comp import get_unique_names
from nomarr.helpers.tag_key_mapping import is_versioned_ml_key, make_short_tag_name

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_nomarr_tag_names(db: Database) -> list[str]:
    """Get all unique tag names used by Nomarr."""
    return get_unique_names(db, nomarr_only=True)


def find_files_matching_tag(
    db: Database,
    name: str,
    operator: str,
    value: Any,
) -> set[int]:
    """Find file IDs matching a tag condition."""
    result = get_file_ids_matching_tag(db, name=name, operator=operator, value=value)
    return set(result) if not isinstance(result, set) else result


def get_short_to_versioned_mapping(
    db: Database,
    namespace: str = "nom",
) -> dict[str, list[str]]:
    """Map short tag names to their versioned storage keys.

    Most short names map to exactly one versioned key, but future
    calibrations could create multiple versions of the same label.
    """
    all_names = get_nomarr_tag_names(db)
    nom_names = [name for name in all_names if name.startswith(f"{namespace}:")]

    mapping: dict[str, list[str]] = {}

    for name in nom_names:
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
    """Resolve a short tag name to its versioned storage key(s)."""
    mapping = get_short_to_versioned_mapping(db, namespace)
    return mapping.get(short_name, [])
