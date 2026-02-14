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
from dataclasses import dataclass

from nomarr.helpers.dto.navidrome_dto import (
    MAX_RULE_GROUP_DEPTH,
    RuleGroup,
    SmartPlaylistFilter,
    TagCondition,
)
from nomarr.helpers.exceptions import PlaylistQueryError

# Maximum query length to prevent ReDoS attacks
MAX_QUERY_LENGTH = 4096



@dataclass
class TokenizedGroup:
    """A tokenized group from parenthesis parsing."""

    content: str
    """Raw content inside this group (without outer parentheses)"""

    depth: int
    """Nesting depth (0 = root level)"""

    start_pos: int
    """Starting position in original query"""

    end_pos: int
    """Ending position in original query"""


def _tokenize_parentheses(
    query: str, max_depth: int = MAX_RULE_GROUP_DEPTH
) -> tuple[str, list[tuple[int, int, int]]]:
    """Tokenize query by parentheses, track depth, and enforce max depth.

    Args:
        query: Query string with potential parentheses
        max_depth: Maximum allowed nesting depth

    Returns:
        Tuple of (query_without_parens, group_ranges)
            - query_without_parens: Query with parentheses removed
            - group_ranges: List of (start, end, depth) tuples for each group

    Raises:
        PlaylistQueryError: If parentheses are unbalanced or depth exceeds max

    Examples:
        >>> _tokenize_parentheses("(a AND b) OR (c AND d)")
        ("a AND b OR c AND d", [(1, 8, 1), (13, 20, 1)])

        >>> _tokenize_parentheses("((a))")
        ("a", [(2, 3, 2)])
    """
    depth = 0
    max_seen_depth = 0
    group_ranges: list[tuple[int, int, int]] = []
    current_group_start = -1

    for i, char in enumerate(query):
        if char == "(":
            depth += 1
            if depth > max_seen_depth:
                max_seen_depth = depth
            if depth > max_depth:
                msg = f"Query nesting depth {depth} exceeds maximum of {max_depth}"
                raise PlaylistQueryError(msg)
            if depth == 1:
                current_group_start = i
        elif char == ")":
            if depth == 0:
                msg = "Unbalanced parentheses: closing ')' without opening '('"
                raise PlaylistQueryError(msg)
            if depth == 1 and current_group_start >= 0:
                # Record this group range
                group_ranges.append((current_group_start + 1, i, 1))
            depth -= 1

    if depth != 0:
        msg = "Unbalanced parentheses: unclosed '('"
        raise PlaylistQueryError(msg)

    # Remove parentheses from query for simpler parsing
    query_without_parens = query.replace("(", "").replace(")", "")

    return query_without_parens, group_ranges


def _find_top_level_operators(query: str) -> list[tuple[int, str]]:
    """Find AND/OR operators at top level (outside parentheses).

    Args:
        query: Query string to scan

    Returns:
        List of (position, operator_type) tuples sorted by position

    Raises:
        PlaylistQueryError: If mixed AND/OR found at same level

    """
    operators: list[tuple[int, str]] = []
    depth = 0
    i = 0

    while i < len(query):
        char = query[i]

        if char == "(":
            depth += 1
            i += 1
        elif char == ")":
            depth -= 1
            i += 1
        elif depth == 0:
            # Check for AND/OR at top level
            # Must be preceded by space or start, followed by space or end
            if (
                i + 3 <= len(query)
                and query[i : i + 3].upper() == "AND"
                and (i + 3 >= len(query) or query[i + 3].isspace())
                and (i == 0 or query[i - 1].isspace())
            ):
                operators.append((i, "AND"))
                i += 3
                continue
            if (
                i + 2 <= len(query)
                and query[i : i + 2].upper() == "OR"
                and (i + 2 >= len(query) or query[i + 2].isspace())
                and (i == 0 or query[i - 1].isspace())
            ):
                operators.append((i, "OR"))
                i += 2
                continue
            i += 1
        else:
            i += 1

    # Verify all operators are same type
    if operators:
        op_types = {op[1] for op in operators}
        if len(op_types) > 1:
            msg = "Mixed AND/OR operators at same level not supported. Use parentheses to group."
            raise PlaylistQueryError(msg)

    return operators


def _split_on_operators(
    query: str, operator_positions: list[tuple[int, str]]
) -> list[str]:
    """Split query string at operator positions.

    Args:
        query: Original query string
        operator_positions: List of (position, operator) from _find_top_level_operators

    Returns:
        List of query segments between operators

    """
    if not operator_positions:
        return [query]

    segments: list[str] = []
    start = 0

    for pos, op in operator_positions:
        # Extract segment before this operator
        segment = query[start:pos]
        segments.append(segment)
        # Move start past the operator
        start = pos + len(op)

    # Add final segment after last operator
    final_segment = query[start:]
    segments.append(final_segment)

    return segments


def _parse_group(query: str, namespace: str, depth: int = 0) -> RuleGroup:
    """Recursively parse a query string into a RuleGroup tree.

    Args:
        query: Query string (may contain nested parentheses)
        namespace: Tag namespace for conditions
        depth: Current nesting depth (for validation)

    Returns:
        RuleGroup with parsed conditions and/or nested groups

    Raises:
        PlaylistQueryError: If syntax invalid or max depth exceeded

    """
    if depth >= MAX_RULE_GROUP_DEPTH:
        msg = f"Maximum nesting depth ({MAX_RULE_GROUP_DEPTH}) exceeded"
        raise PlaylistQueryError(msg)

    query = query.strip()

    if not query:
        msg = "Empty query segment"
        raise PlaylistQueryError(msg)

    # Check if entire query wrapped in outer parentheses
    if query.startswith("(") and query.endswith(")"):
        # Verify these are matching outer parens
        depth_counter = 0
        is_outer_parens = True
        for i, char in enumerate(query):
            if char == "(":
                depth_counter += 1
            elif char == ")":
                depth_counter -= 1
                if depth_counter == 0 and i < len(query) - 1:
                    # Closing paren isn't at the end - not outer parens
                    is_outer_parens = False
                    break

        if is_outer_parens:
            # These are outer parens - strip and recurse
            return _parse_group(query[1:-1], namespace, depth + 1)

    # Find top-level AND/OR operators (outside parentheses)
    operator_positions = _find_top_level_operators(query)

    if not operator_positions:
        # No operators - this is a single condition
        condition = _parse_condition(query, namespace)
        return RuleGroup(logic="AND", conditions=[condition], groups=[])

    # Determine which operator to use (all same type, verified by helper)
    operator = operator_positions[0][1]  # Get operator type from first position

    # Split on operators
    segments = _split_on_operators(query, operator_positions)

    # Parse each segment
    conditions: list[TagCondition] = []
    groups: list[RuleGroup] = []

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # Check if segment is parenthesized
        if segment.startswith("(") and segment.endswith(")"):
            # Check if entire segment is one group
            is_single_group = True
            depth_counter = 0
            for i, char in enumerate(segment):
                if char == "(":
                    depth_counter += 1
                elif char == ")":
                    depth_counter -= 1
                    if depth_counter == 0 and i < len(segment) - 1:
                        is_single_group = False
                        break

            if is_single_group:
                # Recursively parse as nested group
                nested_group = _parse_group(segment[1:-1], namespace, depth + 1)
                groups.append(nested_group)
            else:
                # Complex segment - parse as group without stripping
                nested_group = _parse_group(segment, namespace, depth + 1)
                groups.append(nested_group)
        else:
            # Try to parse as condition
            try:
                condition = _parse_condition(segment, namespace)
                conditions.append(condition)
            except PlaylistQueryError:
                # Might be a complex expression - parse as group
                nested_group = _parse_group(segment, namespace, depth + 1)
                groups.append(nested_group)

    return RuleGroup(
        logic=operator,  # type: ignore[arg-type]  # operator validated by _find_top_level_operators
        conditions=conditions,
        groups=groups,
    )

def parse_smart_playlist_query(query: str, namespace: str = "nom") -> SmartPlaylistFilter:
    """Parse Smart Playlist query into structured filter object.

    This is a PURE function - no SQL generation, no database access.
    Supports nested rule groups with parentheses for complex boolean logic.

    Backward Compatibility:
        Flat queries without parentheses (e.g., "tag:a > 1 AND tag:b > 2")
        are automatically represented as a single root RuleGroup with no
        nested groups. This maintains compatibility with pre-nested query
        behavior - the structure is identical, just wrapped in RuleGroup.

    Args:
        query: Smart Playlist query string (supports nested parentheses)
        namespace: Tag namespace (default: "nom")

    Returns:
        SmartPlaylistFilter with parsed rule groups

    Raises:
        PlaylistQueryError: If query syntax is invalid or too long

    USAGE:
        >>> from nomarr.workflows.navidrome.parse_smart_playlist_query_wf import parse_smart_playlist_query
        >>> # Nested query
        >>> filter = parse_smart_playlist_query("(tag:mood_happy > 0.7 AND tag:energy > 0.6) OR tag:calm > 0.8")
        >>> print(filter.root.logic)  # "OR"
        >>> print(filter.root.groups)  # Has nested groups
        >>> # Flat query (backward compatible)
        >>> filter = parse_smart_playlist_query("tag:mood_happy > 0.7 AND tag:energy > 0.6")
        >>> print(filter.root.logic)  # "AND"
        >>> print(filter.root.groups)  # Empty list - no nested groups

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

    # Validate parenthesis balance and depth before parsing
    try:
        _tokenize_parentheses(query, MAX_RULE_GROUP_DEPTH)
    except PlaylistQueryError:
        # Re-raise with original error message (already has context)
        raise

    # Parse query into tree structure
    root_group = _parse_group(query, namespace, depth=0)

    return SmartPlaylistFilter(root=root_group)


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
    # Order operators from longest to shortest to prevent partial matches
    pattern = r"^tag:(\S+)\s+(notcontains|contains|!=|>|<|=)\s+([^\s].*)$"
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
