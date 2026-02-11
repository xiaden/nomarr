"""Smart Playlist Filter Engine.

Executes parsed smart playlist filters using set operations.
This module sits in the workflows layer and orchestrates:
1. Calling simple persistence queries for each condition
2. Combining results using Python set operations (AND = intersection, OR = union)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.navidrome.tag_query_comp import find_files_matching_tag
from nomarr.helpers.dto.navidrome_dto import STANDARD_TAG_RELS

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


def _execute_single_condition(db: Database, condition: TagCondition) -> set[str]:
    """Execute a single tag condition and return matching file IDs.

    Args:
        db: Database instance
        condition: Single tag condition

    Returns:
        Set of file IDs matching the condition

    """
    # Use unified TagOperations for tag queries
    # Standard tags (year, artist, etc.) have no namespace prefix
    # Nomarr tags (mood, effnet, etc.) have "nom:" prefix
    rel = condition.tag_key

    # Strip any existing "nom:" prefix for lookup
    raw_key = rel.removeprefix("nom:")

    # Standard tags must NOT have prefix; nomarr tags must have it
    if raw_key in STANDARD_TAG_RELS:
        rel = raw_key  # No prefix for standard tags
    elif not rel.startswith("nom:"):
        rel = f"nom:{rel}"  # Add prefix for nomarr tags

    if condition.operator == "contains":
        # String contains query
        return find_files_matching_tag(
            db,
            rel=rel,
            operator="CONTAINS",
            value=str(condition.value),
        )
    # Numeric comparison query
    return find_files_matching_tag(
        db,
        rel=rel,
        operator=condition.operator,
        value=condition.value,
    )
