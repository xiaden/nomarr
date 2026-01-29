"""List libraries component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class ListLibrariesComp:
    """Component for listing libraries."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """
        List all libraries.

        Args:
            enabled_only: If True, only return enabled libraries

        Returns:
            List of library dicts
        """
        return self.db.libraries.list_libraries(enabled_only=enabled_only)
