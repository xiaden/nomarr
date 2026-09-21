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
    mark_scan_started,
)
from nomarr.helpers.exceptions import LibraryOperationConflict

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_setup_workflow(
    db: Database,
    library: Library,
    scan_type: str,
) -> Library:
    """Validate a library and prepare it for scanning.

    This workflow runs synchronously in the service layer before a scan
    workflow is dispatched as a background task.  Any error raised here
    is catchable at the HTTP layer.

    Args:
        db: Database instance.
        library: Domain ``Library`` (natural identity) to scan.
        scan_type: ``"quick"`` or ``"full"`` (used only for logging).

    Returns:
        The domain ``Library`` value being scanned.

    Raises:
        LibraryAlreadyScanningError: If the library is already being scanned.

    """
    try:
        db.library.regions.admit_scan(library)
    except LibraryOperationConflict:
        # Preserve authoritative lifecycle facts for service and transport adapters.
        # Admission owns conflict classification; this workflow must not collapse it
        # into the legacy scan-only exception.
        raise

    interrupted, prev_scan_type = check_interrupted_scan(db, library)
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
        library.name,
        library.name,
    )

    # The setup workflow runs before the background scan starts, so it owns
    # creation of the scan row.  Progress updates require that row to exist.
    mark_scan_started(db, library, scan_type)

    return library
