"""Scan lifecycle component — persistence operations for library scanning.

Wraps scan state tracking calls needed by the scan workflows.  Workflows
call these functions instead of accessing persistence directly.

File-batch upsert, folder cache management, deleted-file cleanup, and
state bootstrap operations were extracted to
``nomarr.components.library.library_scan_file_ops_comp``.

Overlap: concurrent song-domain repair (TASK-song-intent-facade-correction-A)
also edits this file. This change is scoped to the library-scan-domain migration
(P4-S3) — moving all routines from int library ids / scan/pipeline dicts to
domain ``Library`` + ``LibraryScan``/``LibraryPipelineState`` values — and
preserves any concurrent hunks.
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
    SCAN_COMPLETE,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
)
from nomarr.helpers.exceptions import LibraryNotFoundError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------


def is_library_scanning(db: Database, library: Library) -> bool:
    """Return whether the library pipeline is currently in the scanning state.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    Returns:
        ``True`` when the library scan_state equals ``scanning``;
        otherwise ``False``.

    """
    try:
        pipeline_state = get_pipeline_state(db, library)
    except ValueError:
        return False
    return pipeline_state.scan_state == SCAN_IN_PROGRESS


def resolve_library_for_scan(db: Database, library: Library) -> Library:
    """Fetch a library's domain value, raising if not found.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    Returns:
        The re-fetched domain ``Library`` value.

    Raises:
        LibraryNotFoundError: If library not found

    """
    existing = db.library.get_library(library)
    if existing is None:
        msg = f"Library {library.name!r} not found"
        raise LibraryNotFoundError(msg)
    return existing


def check_interrupted_scan(db: Database, library: Library) -> tuple[bool, str | None]:
    """Check whether a previous scan was interrupted.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    Returns:
        Tuple of (was_interrupted, scan_type).  *scan_type* is ``"quick"``
        or ``"full"`` when interrupted, ``None`` otherwise.

    """
    scan = db.library.get_scan(library)
    if scan and scan.status == "in_progress":
        return (True, scan.scan_type)
    return (False, None)


def get_scanning_library_ids(db: Database) -> list[Library]:
    """Return the set of library domain values currently in scanning state.

    Args:
        db: Database instance.

    Returns:
        List of domain ``Library`` values, deduplicated by natural ``name``.

    """
    libraries = get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
    seen: dict[str, Library] = {}
    for library in libraries:
        if library.name not in seen:
            seen[library.name] = library
    return list(seen.values())


def transition_to_scanning(db: Database, library: Library) -> None:
    """Transition a library pipeline into the scanning state.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    """
    transition_pipeline_axis(db, library, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)


def get_library_scan_histories(
    db: Database,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Get scan history for all libraries.

    Builds the scan-history view from the ``LibraryDict`` projection merged by
    ``list_library_records`` (which is itself built from domain ``Library`` +
    ``LibraryScan`` + ``LibraryPipelineState``).

    Args:
        db: Database instance.
        limit: Maximum number of library entries to return. ``None`` for all.

    Returns:
        List of scan info dicts with ``library_id`` (natural ``name``),
        ``name``, ``scanned_at``, and ``scan_status``.

    """
    libraries = list_library_records(db)
    if limit is not None:
        libraries = libraries[:limit]

    return [
        {
            "library_id": lib.name,
            "name": lib.name or "Unknown",
            "scanned_at": lib.scanned_at,
            "scan_status": lib.scan_status,
        }
        for lib in libraries
    ]


# ---------------------------------------------------------------------------
# Scan status tracking
# ---------------------------------------------------------------------------


def mark_scan_started(db: Database, library: Library, scan_type: str) -> None:
    """Record that a scan has started.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)
        scan_type: ``"quick"`` or ``"full"``

    """
    started_at = now_ms().value
    db.library.start_scan(library, scan_type, started_at)


def mark_scan_completed(db: Database, library: Library) -> None:
    """Record that a scan has completed successfully.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    """
    db.library.complete_scan(library, now_ms().value)
    pipeline_state = db.library.get_pipeline_state(library)
    if pipeline_state:
        transition_pipeline_axis(db, library, SCAN_STATE_FIELD, SCAN_COMPLETE)


def update_scan_progress(
    db: Database,
    library: Library,
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
        library: Domain ``Library`` (natural identity)
        status: Scan status (``'idle'``, ``'scanning'``, ``'complete'``, ``'error'``)
        progress: Files processed so far
        total: Total files to scan
        scan_error: Error message (only when ``status='error'``)

    """
    # A progress update is also the scan heartbeat. Keep this separate from
    # started_at so scan duration and the API's start time remain immutable.
    db.library.record_scan_progress(
        library,
        heartbeat_at=now_ms().value,
        status=status,
        progress=progress,
        total=total,
        scan_error=scan_error,
    )


def is_scan_stale(db: Database, library: Library, timeout_ms: int = 300_000) -> bool:
    """Check whether a running scan has exceeded the timeout.

    Args:
        db: Database instance.
        library: Domain ``Library`` (natural identity).
        timeout_ms: Maximum allowed duration in milliseconds (default 5 min).

    Returns:
        ``True`` when the library's scan_state is ``"scanning"`` and the
        ``heartbeat_at`` field from the scan record is older than *timeout_ms*
        from now.

    """
    state = get_pipeline_state(db, library).scan_state
    if state != SCAN_IN_PROGRESS:
        return False

    scan = db.library.get_scan(library)
    if not scan:
        return False

    heartbeat_at = scan.heartbeat_at
    if not isinstance(heartbeat_at, int):
        heartbeat_at = scan.started_at
    if not isinstance(heartbeat_at, int):
        return False

    now_val: int = now_ms().value
    elapsed = now_val - heartbeat_at
    return elapsed > timeout_ms


def on_scan_complete_pipeline_hook(db: Database, library: Library) -> None:
    """Transition pipeline state after scan completion based on file count.

    If the library contains files, transitions the ml axis to ``ML_IN_PROGRESS``.
    Otherwise transitions to ``ML_NOT_PROCESSED``.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity)

    """
    file_count = len(db.library.list_library_song_ids(library))
    next_state = ML_IN_PROGRESS if file_count > 0 else ML_NOT_PROCESSED
    current = get_pipeline_state(db, library)
    if current.ml_state != next_state:
        transition_pipeline_axis(db, library, ML_STATE_FIELD, next_state)
