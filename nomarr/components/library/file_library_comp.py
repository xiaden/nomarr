"""Resolve library ownership for a file."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_file_library_key(db: Database, file_id: str) -> str | None:
    """Return the library ``_key`` that owns the given file.

    Thin component wrapper around the persistence lookup so that
    workflows never call persistence directly.

    Args:
        db: Database instance.
        file_id: Library file document ``_id`` (e.g. ``"library_files/12345"``).

    Returns:
        Library ``_key`` string, or ``None`` if the file does not exist.

    """
    return db.library_files.get_file_library_key(file_id)
