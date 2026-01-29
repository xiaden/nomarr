"""Get library file counts component."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_library_counts(db: Database) -> dict[str, dict[str, int]]:
    """
    Get file and folder counts for all libraries.

    Returns:
        Dict mapping library_id to {"file_count": int, "folder_count": int}
    """
    return db.library_files.get_library_counts()
