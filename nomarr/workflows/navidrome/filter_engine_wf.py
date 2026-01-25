"""
Smart Playlist Filter Engine

Executes parsed smart playlist filters using set operations.
This module sits in the workflows layer and orchestrates:
1. Calling simple persistence queries for each condition
2. Combining results using Python set operations (AND = intersection, OR = union)
"""

from __future__ import annotations

from nomarr.helpers.dto.navidrome_dto import SmartPlaylistFilter, TagCondition
from nomarr.persistence.db import Database


def execute_smart_playlist_filter(db: Database, playlist_filter: SmartPlaylistFilter) -> set[str]:
    """
    Execute a smart playlist filter and return matching file IDs.

    Uses Python set operations to combine conditions:
    - AND conditions: intersection of sets
    - OR conditions: union of sets

    Args:
        db: Database instance
        playlist_filter: Parsed smart playlist filter

    Returns:
        Set of file IDs matching the filter
    """
    # Handle AND conditions (intersection)
    if playlist_filter.all_conditions:
        result_sets = []
        for condition in playlist_filter.all_conditions:
            file_ids = _execute_single_condition(db, condition)
            result_sets.append(file_ids)

        # Intersect all sets (all conditions must match)
        if result_sets:
            return set.intersection(*result_sets)
        return set()

    # Handle OR conditions (union)
    elif playlist_filter.any_conditions:
        result_sets = []
        for condition in playlist_filter.any_conditions:
            file_ids = _execute_single_condition(db, condition)
            result_sets.append(file_ids)

        # Union all sets (any condition can match)
        if result_sets:
            return set.union(*result_sets)
        return set()

    # No conditions - return empty set
    return set()


def _execute_single_condition(db: Database, condition: TagCondition) -> set[str]:
    """
    Execute a single tag condition and return matching file IDs.

    Args:
        db: Database instance
        condition: Single tag condition

    Returns:
        Set of file IDs matching the condition
    """
    # Use unified TagOperations for tag queries
    # Tag key needs "nom:" prefix for nomarr tags
    rel = condition.tag_key
    if not rel.startswith("nom:") and ":" in rel:
        # Already namespaced
        pass
    elif not rel.startswith("nom:"):
        # Add nom: prefix for nomarr tags (most filter engine uses are nomarr tags)
        rel = f"nom:{rel}"

    if condition.operator == "contains":
        # String contains query
        result = db.tags.get_file_ids_matching_tag(
            rel=rel,
            operator="CONTAINS",
            value=str(condition.value),
        )
        return set(result) if not isinstance(result, set) else result
    else:
        # Numeric comparison query
        result = db.tags.get_file_ids_matching_tag(
            rel=rel,
            operator=condition.operator,
            value=condition.value,
        )
        return set(result) if not isinstance(result, set) else result
