"""List libraries component."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


def list_libraries(db: Database, enabled_only: bool = False) -> list[Library]:
    """List libraries, optionally filtered to enabled only (domain values)."""
    return db.library.list_libraries(enabled_only=enabled_only)
