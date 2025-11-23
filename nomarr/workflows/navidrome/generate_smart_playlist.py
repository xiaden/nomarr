"""
Generate Navidrome Smart Playlist (.nsp) workflow.

This module orchestrates the creation of .nsp files by:
1. Parsing the query into a structured filter
2. Fetching matching tracks from the database
3. Building the .nsp structure

No SQL or sqlite3 imports here - all DB access via Database façade.
"""

from typing import Any

from nomarr.persistence.db import Database
from nomarr.workflows.navidrome.parse_smart_playlist_query import (
    SmartPlaylistFilter,
    TagCondition,
    parse_smart_playlist_query,
)

# Operator mappings to Navidrome .nsp format
NSP_OPERATORS: dict[str, str] = {
    ">": "gt",
    "<": "lt",
    ">=": "gt",  # No gte in Navidrome, use gt
    "<=": "lt",  # No lte in Navidrome, use lt
    "=": "is",
    "!=": "isNot",
    "contains": "contains",
}

# Whitelisted sort columns for ORDER BY
VALID_SORT_COLUMNS: set[str] = {"path", "title", "artist", "album", "random"}


def generate_smart_playlist_workflow(
    db: Database,
    query: str,
    *,
    playlist_name: str = "Playlist",
    comment: str = "",
    namespace: str = "nom",
    sort: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Generate a Navidrome Smart Playlist (.nsp) structure.

    This workflow:
    1. Parses the query string into a SmartPlaylistFilter
    2. Converts the filter into .nsp rules format
    3. Adds metadata (name, comment, sort, limit)
    4. Returns a Python dict (service layer can serialize to JSON if needed)

    Args:
        db: Database instance (for potential future validation or track counting)
        query: Smart Playlist query string (e.g., "tag:mood_happy > 0.7 AND tag:energy > 0.6")
        playlist_name: Name of the playlist
        comment: Optional description
        namespace: Tag namespace (default: "nom")
        sort: Sort order string (e.g., "-rating,title")
        limit: Maximum number of tracks

    Returns:
        Dictionary representing .nsp structure with keys:
            - name: playlist name
            - comment: description
            - all or any: list of condition dicts
            - sort: (optional) sort string
            - limit: (optional) max tracks

    Raises:
        ValueError: If query is invalid or sort parameter is unsafe
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")

    # Parse query into structured filter
    playlist_filter = parse_smart_playlist_query(query, namespace)

    # Convert filter to .nsp rules format
    nsp_rules = _convert_filter_to_nsp_rules(playlist_filter, namespace)

    # Build .nsp structure
    nsp: dict[str, Any] = {
        "name": playlist_name,
        "comment": comment or f"Generated from query: {query}",
        **nsp_rules,
    }

    # Add optional sort
    if sort:
        _validate_sort_parameter(sort)
        nsp["sort"] = sort

    # Add optional limit
    if limit is not None and limit > 0:
        if limit > 10000:  # MAX_LIMIT safeguard
            raise ValueError("LIMIT too large (max 10000)")
        nsp["limit"] = limit

    return nsp


def _convert_filter_to_nsp_rules(
    playlist_filter: SmartPlaylistFilter, namespace: str
) -> dict[str, list[dict[str, Any]]]:
    """
    Convert SmartPlaylistFilter to .nsp rules format.

    Args:
        playlist_filter: Parsed filter with all_conditions and any_conditions
        namespace: Tag namespace for stripping prefixes

    Returns:
        Dictionary with either {"all": [...]}, {"any": [...]}, or nested structure
    """
    all_rules = [_tag_condition_to_nsp_rule(cond, namespace) for cond in playlist_filter.all_conditions]
    any_rules = [_tag_condition_to_nsp_rule(cond, namespace) for cond in playlist_filter.any_conditions]

    # Build .nsp structure based on condition types
    if all_rules and not any_rules:
        return {"all": all_rules}
    elif any_rules and not all_rules:
        return {"any": any_rules}
    elif all_rules and any_rules:
        # Mixed logic: nest any_rules inside all_rules
        return {"all": [*all_rules, {"any": any_rules}]}
    else:
        # No conditions (should not happen, parser prevents this)
        return {"all": []}


def _tag_condition_to_nsp_rule(condition: TagCondition, namespace: str) -> dict[str, Any]:
    """
    Convert a single TagCondition to a Navidrome .nsp rule.

    Args:
        condition: TagCondition with tag_key, operator, value
        namespace: Tag namespace to strip from field names

    Returns:
        Dictionary like {nsp_op: {field_name: value}}
        Example: {"gt": {"mood_happy": 0.7}}
    """
    # Remove namespace prefix (Navidrome uses field names without namespace)
    field_name = condition.tag_key
    if field_name.startswith(f"{namespace}:"):
        field_name = field_name[len(namespace) + 1 :]

    # Convert hyphens to underscores (Navidrome field naming convention)
    field_name = field_name.replace("-", "_")

    # Map operator to .nsp format
    nsp_op = NSP_OPERATORS[condition.operator]

    # Build rule
    return {nsp_op: {field_name: condition.value}}


def _validate_sort_parameter(sort: str) -> None:
    """
    Validate sort parameter against whitelist.

    Args:
        sort: Sort string like "-rating,title" or "random"

    Raises:
        ValueError: If sort contains invalid columns
    """
    if not sort or not sort.strip():
        return

    # Split by comma for multi-column sorts
    sort_parts = [part.strip() for part in sort.split(",")]

    for part in sort_parts:
        if not part:
            continue

        # Remove leading "-" for descending sort
        column = part.lstrip("-")

        # Validate against whitelist
        if column.lower() not in VALID_SORT_COLUMNS:
            raise ValueError(f"Invalid sort column: {column}. Allowed columns: {', '.join(sorted(VALID_SORT_COLUMNS))}")
