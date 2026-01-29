"""Get library by ID component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class GetLibraryComp:
    """Component for fetching library records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, library_id: str) -> dict[str, Any] | None:
        """
        Get a library by ID.

        Args:
            library_id: Library _id or _key

        Returns:
            Library dict or None if not found
        """
        return self.db.libraries.get_library(library_id)

    def get_or_error(self, library_id: str) -> dict[str, Any]:
        """
        Get a library by ID or raise an error.

        Args:
            library_id: Library _id or _key

        Returns:
            Library dict

        Raises:
            ValueError: If library not found
        """
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return library
