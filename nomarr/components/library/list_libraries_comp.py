"""List libraries component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def list_libraries(db: Database, enabled_only: bool = False) -> list[dict[str, Any]]:
    """List libraries, optionally filtered to enabled only."""
    return db.libraries.list_libraries(enabled_only=enabled_only)
