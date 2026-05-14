"""Startup-time pruning of orphaned library_files documents.

A library_files document is orphaned when it has no inbound library_contains_file
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
    """Delete all library_files documents that have no ownership edge.

    Cleans all derived data for each orphan in the same order used by
    remove_library: output streams → vectors → tag edges → claim →
    state edges → file document.

    Returns a stats dict with ``files_pruned``.
    """
    orphan_ids = db.library.list_orphaned_file_ids()
    if not orphan_ids:
        logger.debug("[PruneOrphanedFiles] No orphaned files found")
        return {"files_pruned": 0}

    logger.warning("[PruneOrphanedFiles] Found %d orphaned file(s) — pruning", len(orphan_ids))
    db.library.remove_files(orphan_ids)
    return {"files_pruned": len(orphan_ids)}

    logger.info("[PruneOrphanedFiles] Pruned %d orphaned file(s)", len(orphan_ids))
    return {"files_pruned": len(orphan_ids)}
