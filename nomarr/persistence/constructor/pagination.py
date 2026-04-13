"""Pagination utilities for the schema-driven constructor."""

from __future__ import annotations

from typing import Any

DEFAULT_LIMIT = 1000


def inject_pagination(query: str, limit: int | None, offset: int) -> tuple[str, dict[str, Any]]:
    """Append LIMIT/OFFSET clauses to an AQL query using bind vars.

    Returns a (query_fragment, bind_vars) tuple. The caller must merge
    the returned bind_vars into their own bind_vars before executing.
    """
    effective_limit = limit if limit is not None else DEFAULT_LIMIT
    if offset > 0:
        return (
            f"{query.rstrip()} LIMIT @pagination_offset, @pagination_limit",
            {"pagination_offset": offset, "pagination_limit": effective_limit},
        )
    return (
        f"{query.rstrip()} LIMIT @pagination_limit",
        {"pagination_limit": effective_limit},
    )
