"""Scan lifecycle component — persistence operations for library scanning.

Wraps all db.libraries.*, db.library_files.*, and db.library_folders.* calls
needed by the scan workflows.  Workflows call these functions instead of
accessing persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict

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

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _FolderCacheItem(TypedDict):
    """Shape of a library_folders cache record keyed by rel_path."""

    _id: str
    _key: str
    library_id: str
    rel_path: str
    mtime: int
    file_count: int


class _EdgeBootstrap(TypedDict):
    """Edge metadata passed from FileBatchResult to state-edge bootstrapping."""

    normalized_path: str
    type: str  # "ml_tagged" or "reconciled"


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
    return db.libraries.check_interrupted_scan(library_id)


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
    db.libraries.mark_scan_started(library_id, scan_type=scan_type)


def mark_scan_completed(db: Database, library_id: str) -> None:
    """Record that a scan has completed successfully.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    db.libraries.mark_scan_completed(library_id)


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
    db.libraries.update_scan_status(
        library_id,
        status=status,
        progress=progress,
        total=total,
        scan_error=scan_error,
    )


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
    from nomarr.helpers.time_helper import now_ms

    lib = db.libraries.get_library(library_id)
    if not lib:
        return False

    state = get_pipeline_state(db, library_id).get(SCAN_STATE_FIELD)
    if state != SCAN_IN_PROGRESS:
        return False

    started_at = lib.get("scan_started_at") or lib.get("started_at")
    if started_at is None:
        return False

    now_val = now_ms().value
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
    file_count = len(db.library.list_files(filters={"library_id": library_id}, limit=None))
    next_state = ML_IN_PROGRESS if file_count > 0 else ML_NOT_PROCESSED
    transition_pipeline_axis(db, library_id, ML_STATE_FIELD, next_state)


# ---------------------------------------------------------------------------
# File snapshots
# ---------------------------------------------------------------------------


def snapshot_existing_files(
    db: Database,
    library_id: str,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Load all existing library files and check for tagged files.

    Returns a snapshot of what the DB knows before scanning, used for
    comparison during the scan loop.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Tuple of (existing_files_dict, has_tagged_files) where
        *existing_files_dict* maps file path → file document.

    """
    files_tuple = db.library_files.list_library_files(limit=1_000_000, offset=0)
    existing_files_dict: dict[str, dict[str, Any]] = {f["path"]: f for f in files_tuple[0]}
    has_tagged_files = db.file_states.library_has_tagged_files(library_id)
    return existing_files_dict, has_tagged_files


# ---------------------------------------------------------------------------
# Batch file operations
# ---------------------------------------------------------------------------


def upsert_scanned_files(
    db: Database,
    file_entries: list[dict[str, Any]],
    edge_bootstraps: list[_EdgeBootstrap] | None = None,
) -> list[str]:
    """Batch-upsert scanned file documents and optionally bootstrap state edges.

    Args:
        db: Database instance
        file_entries: File documents to upsert
        edge_bootstraps: Optional edge bootstrap metadata from FileBatchResult.
            If provided, creates ml_tagged/reconciled edges for matching files.

    Returns:
        List of document _ids (inserted or updated)

    """
    file_ids = db.library_files.upsert_batch(file_entries)

    if edge_bootstraps:
        # Build path → id map from results
        file_id_by_path: dict[str, str] = {}
        for fid, entry in zip(file_ids, file_entries, strict=True):
            normalized = entry.get("normalized_path")
            if normalized:
                file_id_by_path[normalized] = fid

        bootstrap_file_state_edges(db, edge_bootstraps, file_id_by_path)

    return file_ids


def bootstrap_file_state_edges(
    db: Database,
    edge_bootstraps: list[_EdgeBootstrap],
    file_id_by_path: dict[str, str],
) -> int:
    """Create state edges for files based on scan-time metadata.

    Called after upsert_scanned_files to create ml_tagged/reconciled edges
    for files that should skip ML processing or already have written tags.

    Args:
        db: Database instance
        edge_bootstraps: List of edge bootstrap dicts from FileBatchResult
        file_id_by_path: Map of normalized_path → file _id from upsert results

    Returns:
        Number of edges created

    """
    count = 0
    for bootstrap in edge_bootstraps:
        normalized_path = bootstrap["normalized_path"]
        file_id = file_id_by_path.get(normalized_path)
        if not file_id:
            continue

        if bootstrap["type"] == "ml_tagged":
            db.file_states.set_tagged(file_id)
            count += 1
    return count


def remove_deleted_files(db: Database, paths: list[str]) -> int:
    """Bulk-delete files that are no longer on disk.

    Args:
        db: Database instance
        paths: Absolute file paths to remove

    Returns:
        Number of files deleted

    """
    return db.library_files.bulk_delete_files(paths)


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------


def get_cached_folders(
    db: Database,
    library_id: str,
) -> dict[str, _FolderCacheItem]:
    """Load all cached folder records for a library.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Dict mapping relative folder path → folder record

    """
    return db.library_folders.get_all_folders_for_library(library_id)


def save_folder_record(
    db: Database,
    library_id: str,
    rel_path: str,
    mtime: int,
    file_count: int,
) -> None:
    """Upsert a single folder cache record.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        rel_path: Folder path relative to library root (POSIX-style)
        mtime: Folder modification time
        file_count: Number of audio files in the folder

    """
    db.library_folders.upsert_folder(library_id, rel_path, mtime, file_count)


def cleanup_stale_folders(
    db: Database,
    library_id: str,
    existing_folder_rel_paths: set[str],
) -> None:
    """Delete folder records that no longer exist on disk.

    Logs a warning on failure instead of propagating.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        existing_folder_rel_paths: Set of folder relative paths still on disk

    """
    try:
        db.library_folders.delete_missing_folders(library_id, existing_folder_rel_paths)
    except RuntimeError as e:
        logger.warning("Failed to clean up folder records: %s", e)
