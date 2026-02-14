"""Smart Playlist Filter Engine.

Executes parsed smart playlist filters using set operations.
This module sits in the workflows layer and orchestrates:
1. Calling simple persistence queries for each condition
2. Combining results using Python set operations (AND = intersection, OR = union)

Supports both:
- Full versioned tag keys (nom:happy_essentia21-beta6-dev_...)
- Short user-friendly names (nom-happy-raw) which resolve to versioned keys
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.navidrome.tag_query_comp import find_files_matching_tag
from nomarr.helpers.dto.navidrome_dto import STANDARD_TAG_RELS
from nomarr.helpers.tag_key_mapping import resolve_short_to_versioned_keys

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import SmartPlaylistFilter, TagCondition
    from nomarr.persistence.db import Database
else:
    # Need RuleGroup at runtime for recursive execution
    from nomarr.helpers.dto.navidrome_dto import RuleGroup


def _execute_rule_group(db: Database, rule_group: RuleGroup) -> set[str]:  # type: ignore[name-defined]
    """Recursively execute a rule group and return matching file IDs.

    Combines conditions and nested groups using set operations based on
    the group's logic (AND = intersection, OR = union).

    Args:
        db: Database instance
        rule_group: Rule group to execute (may contain nested groups)

    Returns:
        Set of file IDs matching the rule group

    """
    result_sets: list[set[str]] = []

    # Execute conditions in this group
    for condition in rule_group.conditions:
        file_ids = _execute_single_condition(db, condition)
        result_sets.append(file_ids)

    # Recursively execute nested groups
    for nested_group in rule_group.groups:
        file_ids = _execute_rule_group(db, nested_group)
        result_sets.append(file_ids)

    # Combine results based on logic
    if not result_sets:
        return set()  # Empty group

    if rule_group.logic == "AND":
        # All conditions/groups must match (intersection)
        return set.intersection(*result_sets)
    # logic == "OR"
    # Any condition/group can match (union)
    return set.union(*result_sets)


def execute_smart_playlist_filter(db: Database, playlist_filter: SmartPlaylistFilter) -> set[str]:
    """Execute a smart playlist filter and return matching file IDs.

    Uses Python set operations to combine conditions:
    - AND conditions: intersection of sets
    - OR conditions: union of sets
    Supports nested rule groups for complex boolean logic.

    Args:
        db: Database instance
        playlist_filter: Parsed smart playlist filter with nested groups

    Returns:
        Set of file IDs matching the filter

    """
    return _execute_rule_group(db, playlist_filter.root)


def _resolve_tag_key(db: Database, tag_key: str) -> list[str]:
    """Resolve a tag key to actual storage key(s).

    Handles:
    - Standard tags (artist, album, year) - returned as-is
    - Full versioned keys (nom:happy_essentia21...) - returned with nom: prefix
    - Short names (nom-happy-raw) - resolved to versioned key(s)

    Args:
        db: Database instance
        tag_key: Tag key from user query

    Returns:
        List of storage keys to query (usually 1, may be multiple if short name
        maps to multiple versions)

    """
    # Strip any existing "nom:" prefix for lookup
    raw_key = tag_key.removeprefix("nom:")

    # Standard tags (artist, album, year, etc.) - no prefix needed
    if raw_key in STANDARD_TAG_RELS:
        return [raw_key]

    # Check if this looks like a short name (nom-something or nom_something)
    # Short names use hyphens, storage keys use underscores after nom:
    if tag_key.startswith("nom-") or (tag_key.startswith("nom_") and "essentia" not in tag_key):
        # Try to resolve short name to versioned key(s)
        # Normalize: convert underscores to hyphens for lookup
        short_name = tag_key.replace("_", "-")
        versioned_keys = resolve_short_to_versioned_keys(short_name, db)
        if versioned_keys:
            logger.debug(f"[filter_engine] Resolved '{tag_key}' to {versioned_keys}")
            return versioned_keys
        # If no match found, treat as literal (maybe user knows the exact key)
        logger.warning(f"[filter_engine] Short name '{tag_key}' not found, using as-is")

    # Full versioned key or unknown - ensure nom: prefix for nomarr tags
    if not tag_key.startswith("nom:"):
        return [f"nom:{tag_key}"]
    return [tag_key]


def _execute_single_condition(db: Database, condition: TagCondition) -> set[str]:
    """Execute a single tag condition and return matching file IDs.

    Supports both full versioned tag keys and short user-friendly names.
    Short names are resolved to actual storage keys before querying.

    Args:
        db: Database instance
        condition: Single tag condition

    Returns:
        Set of file IDs matching the condition

    """
    # Resolve tag key to actual storage key(s)
    storage_keys = _resolve_tag_key(db, condition.tag_key)

    # Union results from all resolved keys
    all_matching: set[str] = set()

    for rel in storage_keys:
        if condition.operator == "contains":
            file_ids = find_files_matching_tag(
                db,
                rel=rel,
                operator="CONTAINS",
                value=str(condition.value),
            )
        elif condition.operator == "notcontains":
            file_ids = find_files_matching_tag(
                db,
                rel=rel,
                operator="NOTCONTAINS",
                value=str(condition.value),
            )
        else:
            # Numeric comparison query
            file_ids = find_files_matching_tag(
                db,
                rel=rel,
                operator=condition.operator,
                value=condition.value,
            )
        all_matching.update(file_ids)

    return all_matching
