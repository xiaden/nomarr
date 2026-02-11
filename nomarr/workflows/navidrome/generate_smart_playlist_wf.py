"""Generate Navidrome Smart Playlist (.nsp) workflow.

This module orchestrates the creation of .nsp files by:
1. Parsing the query into a structured filter
2. Fetching matching tracks from the database
3. Building the .nsp structure

No SQL or sqlite3 imports here - all DB access via Database façade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.navidrome_dto import RuleGroup, SmartPlaylistFilter, TagCondition
from nomarr.helpers.exceptions import PlaylistQueryError

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
from nomarr.workflows.navidrome.parse_smart_playlist_query_wf import (
    parse_smart_playlist_query,
)

# Operator mappings to Navidrome .nsp format
NSP_OPERATORS: dict[str, str] = {
    ">": "gt",
    "<": "lt",
    "=": "is",
    "!=": "isNot",
    "contains": "contains",
    "notcontains": "notContains",
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
    """Generate a Navidrome Smart Playlist (.nsp) structure.

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
        PlaylistQueryError: If query is invalid, sort parameter is unsafe, or limit too large

    """
    if not query or not query.strip():
        msg = "Query cannot be empty"
        raise PlaylistQueryError(msg)

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
            msg = "Limit too large (max 10000)"
            raise PlaylistQueryError(msg)
        nsp["limit"] = limit

    return nsp



def _convert_rule_group_to_nsp(rule_group: RuleGroup, namespace: str) -> dict[str, Any]:
    """Convert RuleGroup to .nsp format recursively.

    Args:
        rule_group: Rule group with conditions and/or nested groups
        namespace: Tag namespace for stripping prefixes

    Returns:
        Dictionary with either {"all": [...]}, {"any": [...]}, or nested structure

    """
    rules: list[dict[str, Any]] = []

    # Convert conditions to NSP rules
    for condition in rule_group.conditions:
        rules.append(_tag_condition_to_nsp_rule(condition, namespace))

    # Recursively convert nested groups
    for nested_group in rule_group.groups:
        nested_nsp = _convert_rule_group_to_nsp(nested_group, namespace)
        rules.append(nested_nsp)

    # Wrap in all/any based on logic
    if rule_group.logic == "AND":
        return {"all": rules}
    # logic == "OR"
    return {"any": rules}


def _convert_filter_to_nsp_rules(
    playlist_filter: SmartPlaylistFilter, namespace: str,
) -> dict[str, list[dict[str, Any]]]:
    """Convert SmartPlaylistFilter to .nsp rules format.

    Args:
        playlist_filter: Parsed filter with nested rule groups
        namespace: Tag namespace for stripping prefixes

    Returns:
        Dictionary with either {"all": [...]}, {"any": [...]}, or nested structure

    """
    return _convert_rule_group_to_nsp(playlist_filter.root, namespace)  # type: ignore[return-value]


def _tag_condition_to_nsp_rule(condition: TagCondition, namespace: str) -> dict[str, Any]:
    """Convert a single TagCondition to a Navidrome .nsp rule.

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
    """Validate sort parameter against whitelist.

    Args:
        sort: Sort string like "-rating,title" or "random"

    Raises:
        PlaylistQueryError: If sort contains invalid columns

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
            msg = f"Invalid sort column: {column}. Allowed columns: {', '.join(sorted(VALID_SORT_COLUMNS))}"
            raise PlaylistQueryError(
                msg,
            )
