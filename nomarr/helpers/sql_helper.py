"""
SQL query fragment helpers for safe, parameterized query construction.

These helpers enforce operator and column whitelisting to prevent SQL injection
while maintaining query readability in persistence layer code.

ARCHITECTURE:
- Only persistence/ modules should use these helpers
- Helpers validate and construct SQL fragments, not complete queries
- All user-provided values MUST be passed as parameters, never interpolated
- Whitelists are defined at call sites in persistence/ for clarity

Rules:
- Import only stdlib (no nomarr.* imports)
- No database access or SQL execution here
- Pure string manipulation with validation
"""

from __future__ import annotations


def build_comparison(
    column: str,
    operator: str,
    *,
    allowed_operators: frozenset[str] | None = None,
    allowed_columns: frozenset[str] | None = None,
    allow_expressions: bool = False,
) -> str:
    """
    Build a safe SQL comparison fragment: "column operator ?".

    Args:
        column: Column name or SQL expression to compare
        operator: Comparison operator (will be validated if whitelist provided)
        allowed_operators: Optional set of permitted operators (e.g. {">", ">=", "=", "!="})
        allowed_columns: Optional set of permitted column names
        allow_expressions: If True, allows SQL expressions like "CAST(col AS REAL)"
                          If False, only simple column names allowed

    Returns:
        SQL fragment like "tag_value > ?" ready for parameterized query

    Raises:
        ValueError: If operator or column not in whitelist

    Example:
        >>> sql = build_comparison("price", ">", allowed_operators=frozenset([">", "<", "="]))
        >>> cur.execute(f"SELECT * FROM items WHERE {sql}", (100,))
        >>> sql = build_comparison("CAST(tag_value AS REAL)", ">", allow_expressions=True)
    """
    if allowed_operators is not None and operator not in allowed_operators:
        raise ValueError(f"Invalid operator: '{operator}' not in allowed set: {sorted(allowed_operators)}")

    if allowed_columns is not None and column not in allowed_columns:
        raise ValueError(f"Invalid column: '{column}' not in allowed set: {sorted(allowed_columns)}")

    # If expressions are not allowed, validate column is a safe identifier
    if not allow_expressions and not column.replace("_", "").isalnum():
        raise ValueError(f"Invalid column name: {column!r}")

    return f"{column} {operator} ?"


def build_in_clause(count: int, *, allow_empty: bool = False) -> str:
    """
    Build a safe SQL IN clause with proper number of placeholders.

    Args:
        count: Number of items in the IN list
        allow_empty: If True, return "1=0" for empty lists (no matches)
                     If False, raise ValueError for empty lists

    Returns:
        SQL fragment like "IN (?, ?, ?)" or "1=0" for empty lists

    Raises:
        ValueError: If count is 0 and allow_empty is False

    Example:
        >>> clause = build_in_clause(3)
        >>> cur.execute(f"SELECT * FROM items WHERE id {clause}", (1, 2, 3))
    """
    if count == 0:
        if allow_empty:
            return "1=0"  # Always false condition (no matches)
        raise ValueError("Cannot build IN clause for empty list (use allow_empty=True if intentional)")

    if count < 0:
        raise ValueError(f"Invalid count for IN clause: {count}")

    placeholders = ",".join("?" * count)
    return f"IN ({placeholders})"


def build_order_by(
    column: str | None,
    *,
    allowed_columns: frozenset[str],
    allow_random: bool = False,
    direction: str = "ASC",
) -> str:
    """
    Build a safe ORDER BY clause with column whitelisting.

    Args:
        column: Column name to sort by (or None to skip ORDER BY entirely)
        allowed_columns: Set of permitted column names
        allow_random: If True, allow column="RANDOM()" for random ordering
        direction: Sort direction ("ASC" or "DESC")

    Returns:
        SQL fragment like "ORDER BY price DESC" or empty string if column is None

    Raises:
        ValueError: If column not in whitelist or invalid direction

    Example:
        >>> order = build_order_by("price", allowed_columns=frozenset(["price", "name"]))
        >>> cur.execute(f"SELECT * FROM items {order}")
    """
    if column is None:
        return ""

    direction = direction.upper()
    if direction not in ("ASC", "DESC"):
        raise ValueError(f"Invalid sort direction: {direction!r} (must be ASC or DESC)")

    # Special case: RANDOM() for shuffled results
    if column == "RANDOM()":
        if not allow_random:
            raise ValueError("RANDOM() not allowed (set allow_random=True)")
        return "ORDER BY RANDOM()"

    # Validate column against whitelist
    if column not in allowed_columns:
        raise ValueError(f"Column '{column}' not in allowed set: {sorted(allowed_columns)}")

    # Column name should be safe identifier
    if not column.replace("_", "").isalnum():
        raise ValueError(f"Invalid column name: {column!r}")

    return f"ORDER BY {column} {direction}"


def build_limit_clause(limit: int | None) -> str:
    """
    Build a safe LIMIT clause.

    Args:
        limit: Maximum number of rows (or None to skip LIMIT)

    Returns:
        SQL fragment like "LIMIT 100" or empty string if limit is None

    Raises:
        ValueError: If limit is negative

    Example:
        >>> limit_sql = build_limit_clause(50)
        >>> cur.execute(f"SELECT * FROM items {limit_sql}")
    """
    if limit is None:
        return ""

    if limit < 0:
        raise ValueError(f"Invalid limit: {limit} (must be non-negative)")

    return f"LIMIT {limit}"
