"""Private query helpers for file state AQL mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


def _scalar_int(db: DatabaseLike, query: str, bind_vars: dict[str, Any]) -> int:
    """Execute a scalar AQL query and return its integer result, defaulting to 0."""
    cursor = cast(
        "Cursor",
        db.aql.execute(  # type: ignore[union-attr]
            query,
            bind_vars=cast("dict[str, Any]", bind_vars),
        ),
    )
    return int(next(cursor, 0))
