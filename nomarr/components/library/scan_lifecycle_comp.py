"""Scan lifecycle component — persistence operations for library scanning.

Wraps scan state tracking calls needed by the scan workflows.  Workflows
call these functions instead of accessing persistence directly.

File-batch upsert, folder cache management, deleted-file cleanup, and
state bootstrap operations were extracted to
``nomarr.components.library.library_scan_file_ops_comp``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_records_comp import list_library_records
from nomarr.components.library.library_scan_state_comp import (
    get_libraries_in_axis_state,
    get_pipeline_state,
    transition_pipeline_axis,
)
from nomarr.helpers.constants.pipeline_states import (
    ML_IN_PROGRESS,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
)
from nomarr.helpers.exceptions import LibraryNotFoundError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------


def is_library_scanning(db: Database, library_id: str) -> bool:
    """Return whether the library pipeline is currently in the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        ``True`` when the library scan_state equals ``scanning``;
        otherwise ``False``.

    """
    try:
        pipeline_state = get_pipeline_state(db, library_id)
    except ValueError:
        return False
    return pipeline_state.get(SCAN_STATE_FIELD) == SCAN_IN_PROGRESS


def resolve_library_for_scan(db: Database, library_id: str) -> dict[str, Any]:
    """Fetch a library document, raising if not found.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Library dict

    Raises:
        ValueError: If library not found

    """
    library = db.libraries.get_library(library_id)
    if not library:
        msg = f"Library {library_id} not found"
        raise LibraryNotFoundError(msg)
    return library


def check_interrupted_scan(db: Database, library_id: str) -> tuple[bool, str | None]:
    """Check whether a previous scan was interrupted.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Tuple of (was_interrupted, scan_type).  *scan_type* is ``"quick"``
        or ``"full"`` when interrupted, ``None`` otherwise.

    """
    scan = db.app.get_scan(library_id)
    if scan and scan.get("status") == "in_progress":
        return (True, scan.get("scan_type"))
    return (False, None)


def get_scanning_library_ids(db: Database) -> set[str]:
    """Return the set of library document IDs currently in scanning state.

    Args:
        db: Database instance.

    Returns:
        Set of library ``_id`` strings.  Duplicates from the persistence
        layer are collapsed into a deduplicated set.

    """
    raw = get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
    return set(raw)


def transition_to_scanning(db: Database, library_id: str) -> None:
    """Transition a library pipeline into the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    transition_pipeline_axis(db, library_id, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


def get_library_scan_histories(
    db: Database,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Get scan history for all libraries.

    Iterates library records and builds a simplified scan-history view
    using the scan state already merged by ``list_library_records``.

    Args:
        db: Database instance.
        limit: Maximum number of library entries to return. ``None`` for all.

    Returns:
        List of scan info dicts with ``library_id``, ``name``,
        ``scanned_at``, and ``scan_status``.

    """
    libraries = list_library_records(db)
    if limit is not None:
        libraries = libraries[:limit]

    return [
        {
            "library_id": lib["_id"],
            "name": lib.get("name", "Unknown"),
            "scanned_at": lib.get("scanned_at"),
            "scan_status": lib.get("scan_status"),
        }
        for lib in libraries
    ]


# ---------------------------------------------------------------------------
# Scan status tracking
# ---------------------------------------------------------------------------


def mark_scan_started(db: Database, library_id: str, scan_type: str) -> None:
    """Record that a scan has started.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        scan_type: ``"quick"`` or ``"full"``

    """
    db.app.add_scan(
        library_id,
        {
            "scan_type": scan_type,
            "status": "in_progress",
            "started_at": now_ms().value,
        },
    )


def mark_scan_completed(db: Database, library_id: str) -> None:
    """Record that a scan has completed successfully.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    db.app.update_scan(
        library_id,
        {
            "status": "completed",
            "finished_at": now_ms().value,
        },
    )


def update_scan_progress(
    db: Database,
    library_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    total: int | None = None,
    scan_error: str | None = None,
) -> None:
    """Update scan progress counters and/or status.

    Only updates fields that are explicitly provided.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        status: Scan status (``'idle'``, ``'scanning'``, ``'complete'``, ``'error'``)
        progress: Files processed so far
        total: Total files to scan
        scan_error: Error message (only when ``status='error'``)

    """
    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if progress is not None:
        payload["progress"] = progress
    if total is not None:
        payload["total"] = total
    if scan_error is not None:
        payload["scan_error"] = scan_error
    if payload:
        db.app.update_scan(library_id, payload)


def is_scan_stale(db: Database, library_id: str, timeout_ms: int = 300_000) -> bool:
    """Check whether a running scan has exceeded the timeout.

    Args:
        db: Database instance.
        library_id: Library document ``_id``.
        timeout_ms: Maximum allowed duration in milliseconds (default 5 min).

    Returns:
        ``True`` when the library's scan_state is ``"scanning"`` and the
        ``started_at`` field is older than *timeout_ms* from now.

    """
    lib = db.libraries.get_library(library_id)
    if not lib:
        return False

    state = get_pipeline_state(db, library_id).get(SCAN_STATE_FIELD)
    if state != SCAN_IN_PROGRESS:
        return False

    started_at_raw = lib.get("scan_started_at") or lib.get("started_at")
    if not isinstance(started_at_raw, int):
        return False
    started_at: int = started_at_raw

    now_val: int = now_ms().value
    elapsed = now_val - started_at
    return elapsed > timeout_ms


def on_scan_complete_pipeline_hook(db: Database, library_id: str) -> None:
    """Transition pipeline state after scan completion based on file count.

    If the library contains files, transitions the ml axis to ``ML_IN_PROGRESS``.
    Otherwise transitions to ``ML_NOT_PROCESSED``.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    file_count = len(db.library.list_library_file_ids(library_id))
    next_state = ML_IN_PROGRESS if file_count > 0 else ML_NOT_PROCESSED
    transition_pipeline_axis(db, library_id, ML_STATE_FIELD, next_state)
