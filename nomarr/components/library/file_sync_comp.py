"""File sync component — persistence operations for single-file library sync.

Wraps all db.libraries.*, db.library_files.*, and db.tags.* calls needed
by sync_file_to_library_wf. Workflows call these functions instead of
accessing persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_mutation_comp import (
    set_chromaprint as persist_chromaprint,
)
from nomarr.components.library.library_file_mutation_comp import (
    update_last_tagged_at as persist_last_tagged_at,
)
from nomarr.components.library.library_file_mutation_comp import (
    upsert_library_file as persist_library_file,
)
from nomarr.components.library.library_file_query_comp import get_library_file as fetch_library_file
from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.library.library_records_comp import find_library_containing_path
from nomarr.components.tagging.tag_write_comp import set_song_tags_batch
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED

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
    return find_library_containing_path(db, file_path)


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

    Returns:
        Document ``_id``

    """
    return persist_library_file(
        db,
        path=path,
        library_id=library_id,
        file_size=file_size,
        modified_time=modified_time,
        duration_seconds=duration_seconds,
        artist=artist,
        album=album,
        title=title,
    )


def get_library_file(db: Database, file_path: str) -> dict[str, Any] | None:
    """Get a library file record by path.

    Args:
        db: Database instance
        file_path: File path (absolute or relative)

    Returns:
        File dict or None if not found

    """
    return fetch_library_file(db, file_path)


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
    persist_chromaprint(db, file_id, chromaprint)


def mark_file_tagged(db: Database, file_id: str) -> None:
    """Mark a file as tagged.

    Args:
        db: Database instance
        file_id: Document ``_id``

    """
    transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
    persist_last_tagged_at(db, file_id)


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------


def save_file_tags(
    db: Database,
    file_id: str,
    parsed_tags: dict[str, list[Any]],
) -> None:
    """Write parsed tags for a file.

    Builds a batch of (song_id, name, values) entries and writes them all
    in 3 AQL round-trips instead of 3 per name.

    Args:
        db: Database instance
        file_id: Document ``_id``
        parsed_tags: Mapping of tag name → list of tag values

    """
    entries = [{"song_id": file_id, "name": name, "values": values} for name, values in parsed_tags.items()]
    set_song_tags_batch(db, entries)
