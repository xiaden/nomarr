"""Scan lifecycle orchestration: library resolution, scan lifecycle markers,
progress tracking, heartbeat, and the on_scan_complete pipeline hook."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def _get_library_record(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return one library document by _id or bare key without scan enrichment."""
    normalized_id = normalize_library_id(library_id)
    result = db.library.get_library(normalized_id)
    if not isinstance(result, dict):
        return None
    return result


def _list_library_records(db: Database) -> list[dict[str, Any]]:
    """Return library documents in legacy created-at order with scan fields merged."""
    docs = db.library.list_libraries()
    if not isinstance(docs, list):
        return []

    enriched_docs: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        library_id = str(doc["_id"])
        scan_doc = get_scan_state(db, library_id)
        try:
            pipeline_state = get_pipeline_state(db, library_id)
        except ValueError:
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


def resolve_library_for_scan(db: Database, library_id: str) -> dict[str, Any]:
    """Fetch a library document, raising if not found."""
    library = _get_library_record(db, library_id)
    if not library:
        msg = f"Library {library_id} not found"
        raise LibraryNotFoundError(msg)
    return library


def check_interrupted_scan(db: Database, library_id: str) -> tuple[bool, str | None]:
    """Check whether a previous scan was interrupted.

    Returns (was_interrupted, scan_type) — scan_type is "quick" or "full"
    when interrupted, None otherwise.
    """
    state = get_scan_state(db, library_id)
    if not state:
        return False, None

    started_at = state.get("started_at")
    if not isinstance(started_at, int):
        return False, None

    completed_at = state.get("completed_at")
    scan_type_raw = state.get("scan_type")
    scan_type: str | None = scan_type_raw if isinstance(scan_type_raw, str) else None
    if not isinstance(completed_at, int):
        return True, scan_type
    interrupted = started_at > completed_at
    return interrupted, scan_type if interrupted else None


def is_library_scanning(db: Database, library_id: str) -> bool:
    """Return True when the library scan axis is in the scanning state."""
    state = db.app.get_pipeline_state(library_id)
    if state is None:
        return False
    return state.get(SCAN_STATE_FIELD) == SCAN_IN_PROGRESS


def get_scanning_library_ids(db: Database) -> set[str]:
    """Return the set of library IDs currently in the scanning state."""
    return set(get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS))


def get_library_scan_histories(
    db: Database,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return scan history records for all libraries, including disabled ones."""
    libraries = _list_library_records(db)
    if limit is not None:
        libraries = libraries[:limit]

    histories: list[dict[str, Any]] = []
    for library in libraries:
        library_id = str(library["_id"])
        scan_doc = get_scan_state(db, library_id)
        try:
            pipeline_state: dict[str, str] | None = get_pipeline_state(db, library_id)
        except ValueError:
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


def mark_scan_started(db: Database, library_id: str, scan_type: str) -> None:
    """Record that a scan has started."""
    update_scan_state(
        db,
        library_id,
        started_at=now_ms().value,
        scan_type=scan_type,
    )


def mark_scan_completed(db: Database, library_id: str) -> None:
    """Record that a scan has completed successfully."""
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
    """Update persisted scan progress fields.

    Only updates fields explicitly provided. Pass None for scan_error,
    completed_at, or started_at to clear that field.
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
    """Return the scan heartbeat timestamp for a library, or None if not set."""
    scan_doc = get_scan_state(db, library_id)
    if scan_doc is None:
        return None
    return scan_doc.get("scan_heartbeat")


def is_scan_stale(db: Database, library_id: str, timeout_ms: int = 300000) -> bool:
    """Check whether a scanning library has a stale heartbeat.

    Default timeout is 300000ms (5 minutes).
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
    """Transition a library scan axis into the scanning state."""
    transition_pipeline_axis(db, library_id, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


def on_scan_complete_pipeline_hook(db: Database, library_id: str) -> None:
    """Transition scan axis to scanned, then derive ml axis from file states.

    After a scan completes the scan axis moves to scanned; if untagged files
    exist the ml axis is set to ML_processing.
    """
    transition_pipeline_axis(db, library_id, SCAN_STATE_FIELD, SCAN_COMPLETE)
    from nomarr.components.library.library_file_state_comp import count_untagged_files

    untagged = count_untagged_files(db, library_id)
    if untagged > 0:
        transition_pipeline_axis(db, library_id, ML_STATE_FIELD, ML_IN_PROGRESS)
