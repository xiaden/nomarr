"""Pagination utilities for the schema-driven constructor."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_LIMIT = 1000

_RETURN_RE = re.compile(r"(\bRETURN\b)", re.IGNORECASE)


def inject_pagination(query: str, limit: int | None, offset: int) -> tuple[str, dict[str, Any]]:
    """Insert LIMIT/OFFSET clauses before the final RETURN in an AQL query.

    Semantics:
    - ``limit=None`` and ``offset=0`` → no LIMIT clause is injected (unbounded).
    - ``limit=None`` and ``offset>0`` → LIMIT offset, DEFAULT_LIMIT injected
      (offset requires a limit in AQL).
    - explicit ``limit`` → LIMIT clause injected with that limit.

    Returns a (query, bind_vars) tuple. The caller must merge
    the returned bind_vars into their own bind_vars before executing.
    """
    stripped = query.rstrip()

    # Unbounded: no limit and no offset → return query unchanged.
    if limit is None and offset == 0:
        return (stripped, {})

    # Find the last RETURN keyword and insert LIMIT before it
    match = list(_RETURN_RE.finditer(stripped))
    if not match:
        msg = f"inject_pagination requires a RETURN clause in the query: {stripped}"
        raise ValueError(msg)

    last_return_pos = match[-1].start()
    before_return = stripped[:last_return_pos]
    return_clause = stripped[last_return_pos:]

    effective_limit = limit if limit is not None else DEFAULT_LIMIT

    if offset > 0:
        limit_clause = "LIMIT @pagination_offset, @pagination_limit "
        bind_vars: dict[str, Any] = {"pagination_offset": offset, "pagination_limit": effective_limit}
    else:
        limit_clause = "LIMIT @pagination_limit "
        bind_vars = {"pagination_limit": effective_limit}

    return (f"{before_return}{limit_clause}{return_clause}", bind_vars)
