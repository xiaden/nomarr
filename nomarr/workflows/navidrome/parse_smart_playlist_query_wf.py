"""Smart Playlist query parser.

Parses Smart Playlist query syntax into structured filter objects.
This module is PURE - no SQL, no Database, no sqlite3 imports.

Query Syntax:
    tag:KEY OPERATOR VALUE [AND|OR tag:KEY OPERATOR VALUE ...]

Operators:
    >   - Greater than (numeric)
    <   - Less than (numeric)
    >=  - Greater than or equal
    <=  - Less than or equal
    =   - Equals (numeric or string)
    !=  - Not equals
    contains - String contains (case-insensitive)

Logic Operators:
    AND - All conditions must match (intersection)
    OR  - Any condition can match (union)

    Note: Mixing AND and OR in the same query is NOT supported.
    Use either all AND or all OR. Mixed queries will be rejected with PlaylistQueryError.

Examples:
    tag:mood_happy > 0.7
    tag:mood_happy > 0.7 AND tag:energy > 0.6
    tag:genre = Rock OR tag:genre = Metal
    tag:bpm > 120 AND tag:danceability > 0.8

"""

from __future__ import annotations

import re

from nomarr.helpers.dto.navidrome_dto import SmartPlaylistFilter, TagCondition
from nomarr.helpers.exceptions import PlaylistQueryError

# Maximum query length to prevent ReDoS attacks
MAX_QUERY_LENGTH = 4096


def parse_smart_playlist_query(query: str, namespace: str = "nom") -> SmartPlaylistFilter:
    """Parse Smart Playlist query into structured filter object.

    This is a PURE function - no SQL generation, no database access.

    Args:
        query: Smart Playlist query string
        namespace: Tag namespace (default: "nom")

    Returns:
        SmartPlaylistFilter with parsed conditions

    Raises:
        PlaylistQueryError: If query syntax is invalid or too long

    USAGE:
        >>> from nomarr.workflows.navidrome.parse_smart_playlist_query_wf import parse_smart_playlist_query
        >>> filter = parse_smart_playlist_query("tag:mood_happy > 0.7 AND tag:energy > 0.6")
        >>> print(filter.all_conditions)
        >>> print(filter.is_simple_and)

    """
    if not query or not query.strip():
        msg = "Query cannot be empty"
        raise PlaylistQueryError(msg)

    # Enforce query length limit to prevent ReDoS attacks
    if len(query) > MAX_QUERY_LENGTH:
        msg = f"Query too long (max {MAX_QUERY_LENGTH} characters)"
        raise PlaylistQueryError(msg)

    # Normalize whitespace
    query = " ".join(query.split())

    # Tokenize into conditions and logic operators
    condition_strings, operators = _tokenize_query(query)

    if not condition_strings:
        msg = "No valid conditions found in query"
        raise PlaylistQueryError(msg)

    # Parse each condition
    conditions: list[tuple[TagCondition, str | None]] = []

    for i, cond_str in enumerate(condition_strings):
        tag_cond = _parse_condition(cond_str, namespace)

        # Determine logic operator for this condition
        # First condition has no logic operator
        logic = operators[i - 1] if i > 0 else None
        conditions.append((tag_cond, logic))

    if not conditions:
        msg = "No valid conditions found in query"
        raise PlaylistQueryError(msg)

    # Group conditions by logic operator
    logic_types = {logic for _, logic in conditions[1:] if logic}

    if not logic_types or logic_types == {"AND"}:
        # All AND conditions - must match all
        all_conds = [cond for cond, _ in conditions]
        any_conds = []
    elif logic_types == {"OR"}:
        # All OR conditions - must match any
        all_conds = []
        any_conds = [cond for cond, _ in conditions]
    else:
        # Mixed AND/OR logic is not supported
        # Reject with clear error message
        msg = "Mixed AND/OR operators are not supported. Use either all AND or all OR in your query."
        raise PlaylistQueryError(
            msg,
        )

    return SmartPlaylistFilter(all_conditions=all_conds, any_conditions=any_conds)


def _tokenize_query(query: str) -> tuple[list[str], list[str]]:
    """Tokenize query into conditions and logic operators using linear-time algorithm.

    This replaces re.split() to avoid ReDoS vulnerabilities from nested quantifiers.

    Args:
        query: Query string with AND/OR operators

    Returns:
        Tuple of (conditions, operators) where:
            - conditions: List of condition strings
            - operators: List of "AND"/"OR" operators (uppercase)

    Example:
        >>> _tokenize_query("tag:a > 1 AND tag:b < 2 OR tag:c = 3")
        (["tag:a > 1", "tag:b < 2", "tag:c = 3"], ["AND", "OR"])

    """
    conditions = []
    operators = []

    # Use regex finditer for linear-time tokenization
    # \b ensures word boundaries (prevents matching "BAND", "FORK", etc.)
    pattern = re.compile(r"\b(AND|OR)\b", re.IGNORECASE)

    last_pos = 0
    for match in pattern.finditer(query):
        # Extract condition between last position and current match
        condition = query[last_pos : match.start()].strip()
        if condition:
            conditions.append(condition)

        # Extract operator and normalize to uppercase
        operators.append(match.group(1).upper())
        last_pos = match.end()

    # Extract final condition after last operator
    final_condition = query[last_pos:].strip()
    if final_condition:
        conditions.append(final_condition)

    return conditions, operators


def _parse_condition(condition: str, namespace: str) -> TagCondition:
    """Parse a single condition string into TagCondition.

    Args:
        condition: Single condition string (e.g., "tag:mood_happy > 0.7")
        namespace: Tag namespace to prepend if not present

    Returns:
        TagCondition object

    Raises:
        PlaylistQueryError: If condition syntax is invalid

    """
    # Pattern: tag:KEY OPERATOR VALUE
    # Use [^\s].* instead of .+ to prevent ReDoS (catastrophic backtracking)
    pattern = r"^tag:(\S+)\s+(>=|<=|!=|>|<|=|contains)\s+([^\s].*)$"
    match = re.match(pattern, condition.strip(), re.IGNORECASE)

    if not match:
        msg = f"Invalid condition syntax: {condition}"
        raise PlaylistQueryError(msg)

    tag_key, operator, value = match.groups()
    operator = operator.lower()

    # Add namespace prefix if not present
    full_tag_key = f"{namespace}:{tag_key}" if not tag_key.startswith(f"{namespace}:") else tag_key

    # Convert value to appropriate type
    value = value.strip().strip('"').strip("'")

    # Try to convert to number
    typed_value: float | int | str
    try:
        typed_value = float(value) if "." in value else int(value)
    except ValueError:
        # Keep as string
        typed_value = value

    return TagCondition(tag_key=full_tag_key, operator=operator, value=typed_value)  # type: ignore[arg-type]
