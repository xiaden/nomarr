"""File sync component — persistence operations for single-file library sync.

Wraps all db.libraries.*, db.library_files.*, and db.tags.* calls needed
by sync_file_to_library_wf. Workflows call these functions instead of
accessing persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.components.infrastructure.path_comp import LibraryPath
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Library lookup
# ---------------------------------------------------------------------------


def find_library_for_file(db: Database, file_path: str) -> dict[str, Any] | None:
    """Find the library that contains the given file path.

    Args:
        db: Database instance
        file_path: Absolute file path

    Returns:
        Library dict if found, None otherwise

    """
    return db.libraries.find_library_containing_path(file_path)


# ---------------------------------------------------------------------------
# File record operations
# ---------------------------------------------------------------------------


def upsert_library_file(
    db: Database,
    path: LibraryPath,
    library_id: str,
    file_size: int,
    modified_time: int,
    *,
    duration_seconds: float | None = None,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    has_nomarr_namespace: bool | None = None,
    last_written_mode: str | None = None,
) -> str:
    """Insert or update a library file record.

    Args:
        db: Database instance
        path: Validated LibraryPath
        library_id: Library document ``_id``
        file_size: File size in bytes
        modified_time: Last modified timestamp (ms)
        duration_seconds: Audio duration
        artist: Artist name
        album: Album name
        title: Track title
        has_nomarr_namespace: Whether file has nomarr tags
        last_written_mode: Inferred write mode from existing file tags

    Returns:
        Document ``_id``

    """
    return db.library_files.upsert_library_file(
        path=path,
        library_id=library_id,
        file_size=file_size,
        modified_time=modified_time,
        duration_seconds=duration_seconds,
        artist=artist,
        album=album,
        title=title,
        has_nomarr_namespace=has_nomarr_namespace,
        last_written_mode=last_written_mode,
    )


def get_library_file(db: Database, file_path: str) -> dict[str, Any] | None:
    """Get a library file record by path.

    Args:
        db: Database instance
        file_path: File path (absolute or relative)

    Returns:
        File dict or None if not found

    """
    return db.library_files.get_library_file(file_path)


# ---------------------------------------------------------------------------
# File metadata updates
# ---------------------------------------------------------------------------


def set_chromaprint(db: Database, file_id: str, chromaprint: str) -> None:
    """Store a chromaprint fingerprint for a file.

    Args:
        db: Database instance
        file_id: Document ``_id``
        chromaprint: Chromaprint fingerprint string

    """
    db.library_files.set_chromaprint(file_id, chromaprint)


def mark_file_tagged(db: Database, file_id: str, tagged_version: str) -> None:
    """Mark a file as tagged with the given version.

    Args:
        db: Database instance
        file_id: Document ``_id``
        tagged_version: Tagger version string

    """
    db.library_files.mark_file_tagged(file_id, tagged_version)


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------


def save_file_tags(
    db: Database,
    file_id: str,
    parsed_tags: dict[str, list[Any]],
) -> None:
    """Write parsed tags for a file.

    Iterates over tag rel→values pairs and calls ``set_song_tags``
    for each.

    Args:
        db: Database instance
        file_id: Document ``_id``
        parsed_tags: Mapping of tag rel → list of tag values

    """
    for rel, values in parsed_tags.items():
        db.tags.set_song_tags(file_id, rel, values)
