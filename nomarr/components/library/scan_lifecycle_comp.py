"""Scan lifecycle component — orchestration-only.

Extracted pipeline-state management to ``library_scan_state_comp`` and
file/folder scan operations to ``library_scan_file_ops_comp``.  This module
retains orchestration glue: library resolution, scan lifecycle markers,
progress tracking, heartbeat, and the ``on_scan_complete_pipeline_hook``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_id_comp import normalize_library_id
from nomarr.components.library.library_scan_state_comp import (
    _pipeline_state_to_scan_status,
    get_libraries_in_axis_state,
    get_pipeline_state,
    get_scan_state,
    transition_pipeline_axis,
    update_scan_state,
)
from nomarr.helpers.constants.pipeline_states import (
    ML_IN_PROGRESS,
    ML_STATE_FIELD,
    SCAN_COMPLETE,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
)
from nomarr.helpers.exceptions import LibraryNotFoundError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


_UNSET: object = object()


# ---------------------------------------------------------------------------
# Library record helpers
# ---------------------------------------------------------------------------


def _get_library_record(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return one library document by ``_id`` or bare key without scan enrichment."""
    normalized_id = normalize_library_id(library_id)
    return cast("dict[str, Any] | None", db.library.get_library(normalized_id))


def _list_library_records(db: Database) -> list[dict[str, Any]]:
    """Return library documents in legacy created-at order with scan fields merged."""
    docs = cast("list[dict[str, Any]]", db.library.list_libraries())

    enriched_docs: list[dict[str, Any]] = []
    for doc in docs:
        library_id = str(doc["_id"])
        scan_doc = get_scan_state(db, library_id)
        try:
            pipeline_state = get_pipeline_state(db, library_id)
        except Exception:
            pipeline_state = None

        enriched_docs.append(
            {
                **doc,
                "scan_status": _pipeline_state_to_scan_status(pipeline_state, scan_doc),
                "scan_progress": 0 if scan_doc is None else scan_doc.get("files_processed", 0),
                "scan_total": 0 if scan_doc is None else scan_doc.get("files_total", 0),
                "scanned_at": None if scan_doc is None else scan_doc.get("completed_at"),
                "scan_error": None if scan_doc is None else scan_doc.get("error"),
                "last_scan_started_at": None if scan_doc is None else scan_doc.get("started_at"),
                "scan_type_in_progress": None if scan_doc is None else scan_doc.get("scan_type"),
            }
        )

    return enriched_docs


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------


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
    library = _get_library_record(db, library_id)
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
    state = get_scan_state(db, library_id)
    if not state:
        return False, None

    started_at = state.get("started_at")
    if started_at is None:
        return False, None

    completed_at = state.get("completed_at")
    scan_type = cast("str | None", state.get("scan_type"))
    if completed_at is None:
        return True, scan_type
    interrupted = cast("int", started_at) > cast("int", completed_at)
    return interrupted, scan_type if interrupted else None


def is_library_scanning(db: Database, library_id: str) -> bool:
    """Return whether the library scan axis is currently in the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        ``True`` when the library scan axis is ``scanning``; otherwise ``False``.

    """
    state = db.app.get_pipeline_state(library_id)
    if state is None:
        return False
    return state.get(SCAN_STATE_FIELD) == SCAN_IN_PROGRESS


def get_scanning_library_ids(db: Database) -> set[str]:
    """Return the set of library IDs currently in the scanning scan state."""
    return set(get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS))


def get_library_scan_histories(
    db: Database,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return scan history records for all libraries, including disabled ones.

    Args:
        db: Database connection.
        limit: Maximum number of records to return. None for all.

    """
    libraries = _list_library_records(db)
    if limit is not None:
        libraries = libraries[:limit]

    histories: list[dict[str, Any]] = []
    for library in libraries:
        library_id = str(library["_id"])
        scan_doc = get_scan_state(db, library_id)
        try:
            pipeline_state: dict[str, str] | None = get_pipeline_state(db, library_id)
        except Exception:
            pipeline_state = None

        histories.append(
            {
                "library_id": library_id,
                "name": library.get("name", "Unknown"),
                "scanned_at": library.get("scanned_at"),
                "scan_status": _pipeline_state_to_scan_status(
                    pipeline_state,
                    scan_doc,
                ),
            }
        )

    return histories


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
    update_scan_state(
        db,
        library_id,
        started_at=now_ms().value,
        scan_type=scan_type,
    )


def mark_scan_completed(db: Database, library_id: str) -> None:
    """Record that a scan has completed successfully.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    update_scan_state(
        db,
        library_id,
        completed_at=now_ms().value,
        started_at=None,
        scan_type=None,
    )


def update_scan_progress(
    db: Database,
    library_id: str,
    *,
    progress: int | None = None,
    total: int | None = None,
    scan_error: str | None | object = _UNSET,
    completed_at: int | None | object = _UNSET,
    started_at: int | None | object = _UNSET,
    heartbeat: bool = False,
) -> None:
    """Update persisted scan progress fields on the scan document.

    Only updates fields that are explicitly provided. Pass ``None`` for
    ``scan_error``, ``completed_at``, or ``started_at`` to clear that field.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        progress: Files processed so far
        total: Total files to scan
        scan_error: Error message to persist on the scan document, or ``None`` to clear it
        completed_at: Completion timestamp in milliseconds, or ``None`` to clear it
        started_at: Start timestamp in milliseconds, or ``None`` to clear it
        heartbeat: If True, updates the scan_heartbeat timestamp to now

    """
    update_fields: dict[str, Any] = {}
    if progress is not None:
        update_fields["files_processed"] = progress
    if total is not None:
        update_fields["files_total"] = total
    if scan_error is not _UNSET:
        update_fields["error"] = scan_error
    if completed_at is not _UNSET:
        update_fields["completed_at"] = completed_at
    if started_at is not _UNSET:
        update_fields["started_at"] = started_at
    if heartbeat:
        update_fields["scan_heartbeat"] = now_ms().value

    if update_fields:
        update_scan_state(db, library_id, **update_fields)


def get_scan_heartbeat(db: Database, library_id: str) -> int | None:
    """Return the scan heartbeat timestamp for a library.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Heartbeat timestamp in milliseconds, or None if not set.

    """
    scan_doc = get_scan_state(db, library_id)
    if scan_doc is None:
        return None
    return scan_doc.get("scan_heartbeat")


def is_scan_stale(db: Database, library_id: str, timeout_ms: int = 300000) -> bool:
    """Check whether a scanning library has a stale heartbeat.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        timeout_ms: Maximum age of heartbeat in milliseconds before considered stale.
            Defaults to 300000 (5 minutes).

    Returns:
        True if the scan is stale (heartbeat older than timeout), False otherwise.

    """
    state = db.app.get_pipeline_state(library_id)
    if state is None or state.get(SCAN_STATE_FIELD) != SCAN_IN_PROGRESS:
        return False

    heartbeat = get_scan_heartbeat(db, library_id)
    if heartbeat is None:
        scan_doc = get_scan_state(db, library_id)
        started_at = scan_doc.get("started_at") if scan_doc else None
        if started_at is None:
            return False
        heartbeat = started_at

    age_ms = now_ms().value - heartbeat
    return age_ms > timeout_ms


def transition_to_scanning(db: Database, library_id: str) -> None:
    """Transition a library scan axis into the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    transition_pipeline_axis(db, library_id, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


def on_scan_complete_pipeline_hook(db: Database, library_id: str) -> None:
    """Transition scan axis to scanned, then derive ml axis from file states.

    After a scan completes:
    - scan axis to scanned
    - ml axis to ML_processing if untagged files exist, else stays where it is

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    transition_pipeline_axis(db, library_id, SCAN_STATE_FIELD, SCAN_COMPLETE)
    from nomarr.components.library.library_file_state_comp import count_untagged_files

    untagged = count_untagged_files(db, library_id)
    if untagged > 0:
        transition_pipeline_axis(db, library_id, ML_STATE_FIELD, ML_IN_PROGRESS)
