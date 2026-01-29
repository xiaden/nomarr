"""Get library by ID component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_library(db: Database, library_id: str) -> dict[str, Any] | None:
    """
    Get a library by ID.

    Args:
        db: Database instance
        library_id: Library _id or _key

    Returns:
        Library dict or None if not found
    """
    return db.libraries.get_library(library_id)


def get_library_or_error(db: Database, library_id: str) -> dict[str, Any]:
    """
    Get a library by ID or raise an error.

    Args:
        db: Database instance
        library_id: Library _id or _key

    Returns:
        Library dict

    Raises:
        ValueError: If library not found
    """
    library = db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library not found: {library_id}")
    return library
