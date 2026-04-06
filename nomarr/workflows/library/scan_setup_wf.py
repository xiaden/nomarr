"""Pre-scan setup workflow.

Validates the library is ready to scan, guards against concurrent scans,
and sets scan_status to 'scanning' before the background task is launched.
Raises typed exceptions so the HTTP layer can map them to the correct status codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.scan_lifecycle_comp import (
    check_interrupted_scan,
    resolve_library_for_scan,
    transition_to_scanning,
    update_scan_progress,
)
from nomarr.helpers.exceptions import LibraryAlreadyScanningError

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_setup_workflow(
    db: Database,
    library_id: str,
    scan_type: str,
) -> dict[str, Any]:
    """Validate a library and prepare it for scanning.

    This workflow runs synchronously in the service layer before a scan
    workflow is dispatched as a background task.  Any error raised here
    is catchable at the HTTP layer.

    Args:
        db: Database instance.
        library_id: Library document ``_id``.
        scan_type: ``"quick"`` or ``"full"`` (used only for logging).

    Returns:
        The library document dict.

    Raises:
        LibraryNotFoundError: If no library with the given ID exists.
        LibraryAlreadyScanningError: If the library is already being scanned.

    """
    library = resolve_library_for_scan(db, library_id)  # raises LibraryNotFoundError

    if library.get("scan_status") == "scanning":
        msg = f"Library {library_id} is already being scanned"
        raise LibraryAlreadyScanningError(msg)

    interrupted, prev_scan_type = check_interrupted_scan(db, library_id)
    if interrupted:
        logger.warning(
            "Detected interrupted %s scan for library %s — continuing with new %s scan",
            prev_scan_type or "unknown",
            library["name"],
            scan_type,
        )

    logger.info(
        "Starting %s scan for library %s (%s)",
        scan_type,
        library_id,
        library["name"],
    )

    update_scan_progress(db, library_id, status="scanning", progress=0, total=0)
    transition_to_scanning(db, library_id)

    return library
