"""Pre-scan setup workflow.

Validates the library is ready to scan, guards against concurrent scans,
initializes scan progress counters, and moves the pipeline into scanning
before the background task is launched. Raises typed exceptions so the HTTP
layer can map them to the correct status codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.scan_lifecycle_comp import (
    check_interrupted_scan,
    is_library_scanning,
    mark_scan_started,
    resolve_library_for_scan,
    transition_to_scanning,
)
from nomarr.helpers.exceptions import DuplicateEntityError, LibraryAlreadyScanningError

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import LibraryDict
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_setup_workflow(
    db: Database,
    library_id: int,
    scan_type: str,
) -> LibraryDict:
    """Validate a library and prepare it for scanning.

    This workflow runs synchronously in the service layer before a scan
    workflow is dispatched as a background task.  Any error raised here
    is catchable at the HTTP layer.

    Args:
        db: Database instance.
        library_id: Library document ``id``.
        scan_type: ``"quick"`` or ``"full"`` (used only for logging).

    Returns:
        The library document dict.

    Raises:
        LibraryNotFoundError: If no library with the given ID exists.
        LibraryAlreadyScanningError: If the library is already being scanned.

    """
    library = resolve_library_for_scan(db, int(library_id))  # raises LibraryNotFoundError

    if is_library_scanning(db, int(library_id)):
        msg = f"Library {library_id} is already being scanned"
        raise LibraryAlreadyScanningError(msg)

    interrupted, prev_scan_type = check_interrupted_scan(db, int(library_id))
    if interrupted:
        logger.warning(
            "Detected interrupted %s scan for library %s — continuing with new %s scan",
            prev_scan_type or "unknown",
            library.name,
            scan_type,
        )

    logger.info(
        "Starting %s scan for library %s (%s)",
        scan_type,
        library_id,
        library.name,
    )

    # The setup workflow runs before the background scan starts, so it owns
    # creation of the scan row.  Progress updates require that row to exist.
    try:
        # The database enforces one in-progress row per library.  This insert
        # is the atomic part of the guard: two requests may both observe the
        # old axis value, but only one can claim the active scan row.
        mark_scan_started(db, int(library_id), scan_type)
    except DuplicateEntityError:
        msg = f"Library {library_id} is already being scanned"
        raise LibraryAlreadyScanningError(msg) from None

    transition_to_scanning(db, int(library_id))

    return library
