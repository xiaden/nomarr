"""List libraries component."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dto.repo_dto import LibraryRow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def list_libraries(db: Database, enabled_only: bool = False) -> list[LibraryRow]:
    """List libraries, optionally filtered to enabled only."""
    return db.library.list_libraries(enabled_only=enabled_only)
