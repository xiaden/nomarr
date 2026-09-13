"""Persistence wrappers for the file tag-writing workflow.

Absorbs the intent-level `db.library.*` / `db.app.*` calls used by
``write_file_tags_wf`` so the workflow never touches persistence directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.reconciliation_comp import release_claim

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File retrieval
# ---------------------------------------------------------------------------


def get_file_for_writing(
    db: Database,
    song: SongIdentity,
) -> Song | None:
    """Resolve a semantic song locator to its domain ``Song`` value."""
    return db.library.get_song(song)


# ---------------------------------------------------------------------------
# Library root resolution
# ---------------------------------------------------------------------------


def resolve_library_root(
    db: Database,
    library: Library,
) -> Path | None:
    """Return the library's root path, or ``None`` if the library is missing."""
    library_doc = get_library_record(db, library, include_scan=False)
    if not library_doc:
        return None
    return Path(library_doc.root_path)


# ---------------------------------------------------------------------------
# Claim / state mutation
# ---------------------------------------------------------------------------


def release_file_claim(
    db: Database,
    song: SongIdentity,
    worker_id: str,
) -> None:
    """Release a write claim without updating projection state.

    Swallows exceptions so callers in error paths don't need try/except.
    """
    try:
        release_claim(db, song, worker_id)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "[file_write_comp] Failed to release claim for %s: %s",
            song.normalized_path,
            exc,
            exc_info=True,
        )
