"""Startup-time pruning of orphaned tracks.

A song document is orphaned when it has no inbound library_contains_file
edge — this happens when a library was deleted while the deletion code was broken,
or when a scan was interrupted after writing file docs but before writing the
ownership edges.

Orphaned files are invisible to all scan and ML pipeline queries (which traverse
ownership edges), but they persist in the collection and bloat counts. They also
prevent re-adding the same file path via a fresh scan because the path-uniqueness
check finds the old document and returns it as "existing".

This workflow detects and fully cleans orphaned files at startup (after migrations).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def prune_orphaned_files_workflow(db: Database) -> dict[str, int]:
    """Delete all tracks that have no owning library.

    Delegates the locator-free maintenance removal to the single facade intent
    ``LibrarySongsDb.prune_orphaned_songs``: persistence resolves the orphan row
    handles privately and deletes each orphan's full derived set (FK CASCADE). No
    generated ``songs.id`` or ``library_id`` crosses this boundary — only the
    removed count is returned.

    Returns a stats dict with ``files_pruned``.
    """
    removed = db.library.prune_orphaned_songs()
    if removed == 0:
        logger.debug("[PruneOrphanedFiles] No orphaned files found")
    else:
        logger.warning("[PruneOrphanedFiles] Pruned %d orphaned file(s)", removed)
    return {"files_pruned": removed}
