"""Scan lifecycle component — sub-facade-backed persistence helpers.

Owns the small amount of multi-collection orchestration required for library
scan state and folder-cache persistence via ``db.app`` and ``db.library``.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_query_comp import (
    count_library_files,
    get_existing_file_paths,
    list_library_files,
)
from nomarr.components.library.library_file_state_comp import (
    initialize_file_states_batch,
    library_has_tagged_files,
    transition_file_state,
)
from nomarr.components.library.library_id_comp import library_key_from_ref, normalize_library_id
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
    PIPELINE_SCANNING,
)
from nomarr.helpers.exceptions import LibraryNotFoundError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


_UNSET: object = object()
_PIPELINE_SCANNING_KEY: str = PIPELINE_SCANNING.rsplit("/", 1)[-1]
_DEFAULT_SCAN_FIELDS: dict[str, Any] = {
    "files_processed": 0,
    "files_total": 0,
    "completed_at": None,
    "started_at": None,
    "error": None,
    "scan_type": None,
}


def _pipeline_state_to_scan_status(pipeline_state: str | None, scan_doc: dict[str, Any] | None) -> str:
    """Derive legacy scan_status string from pipeline state and scan doc.

    Rules:
        - pipeline_state == "scanning" -> "scanning"
        - scan_doc.error present       -> "error"
        - scan_doc.completed_at set    -> "complete"
        - otherwise                    -> "idle"
    """
    if pipeline_state == "scanning":
        return "scanning"
    if scan_doc and scan_doc.get("error"):
        return "error"
    if scan_doc and scan_doc.get("completed_at"):
        return "complete"
    return "idle"


def _scan_doc_id(library_id: str) -> str:
    """Return the canonical scan document id for a library."""
    return f"library_scans/{library_key_from_ref(library_id)}"


def _default_scan_doc(library_id: str) -> dict[str, Any]:
    """Build the canonical default scan document payload."""
    library_key = library_key_from_ref(library_id)
    return {
        "_key": library_key,
        "library_key": library_key,
        **_DEFAULT_SCAN_FIELDS,
    }


def _folder_key(library_id: str, folder_path: str) -> str:
    """Generate the legacy-stable folder `_key` from library id and relative path."""
    composite = f"{library_id}/{folder_path}"
    return hashlib.md5(composite.encode("utf-8")).hexdigest()


def _folder_doc_id(library_id: str, folder_path: str) -> str:
    """Return the canonical folder document id for a library/path pair."""
    return f"library_folders/{_folder_key(library_id, folder_path)}"


def _folder_doc(
    library_id: str,
    folder_path: str,
    mtime: int,
    file_count: int,
) -> dict[str, Any]:
    """Build the folder-cache document persisted for quick scans."""
    return {
        "_key": _folder_key(library_id, folder_path),
        "path": folder_path,
        "library_key": library_key_from_ref(library_id),
        "mtime": mtime,
        "file_count": file_count,
        "last_scanned_at": now_ms().value,
    }


def ensure_scan_state(db: Database, library_id: str) -> dict[str, Any]:
    """Return the scan document for a library, creating or repairing it when needed."""
    library_key = library_key_from_ref(library_id)
    scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id))

    if scan_doc is None:
        default_doc = _default_scan_doc(library_id)
        db.app.add_scan(library_id, default_doc)
        scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id)) or default_doc
    elif scan_doc.get("library_key") != library_key:
        repaired_doc = {
            **_DEFAULT_SCAN_FIELDS,
            **scan_doc,
            "_key": library_key,
            "library_key": library_key,
        }
        db.app.remove_scan(library_id)
        db.app.add_scan(library_id, repaired_doc)
        scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id)) or repaired_doc

    return scan_doc


def get_scan_state(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return the scan document for a library, repairing legacy rows when found."""
    scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id))
    if scan_doc is None:
        return None
    if scan_doc.get("library_key") != library_key_from_ref(library_id):
        return ensure_scan_state(db, library_id)
    return scan_doc


def update_scan_state(db: Database, library_id: str, **fields: Any) -> dict[str, Any]:
    """Persist scan-state changes through the constructor-backed namespace."""
    scan_doc = ensure_scan_state(db, library_id)
    if not fields:
        return scan_doc

    db.app.update_scan(library_id, fields)
    refreshed = cast("dict[str, Any] | None", db.app.get_scan(library_id))
    if refreshed is not None:
        return refreshed
    return {**scan_doc, **fields}


def transition_pipeline_state(db: Database, library_id: str, next_state: str) -> None:
    """Persist a library's current pipeline state via the constructor namespace."""
    db.app.update_pipeline_state(library_id, next_state)


def delete_pipeline_state(db: Database, library_id: str) -> int:
    """Delete a library's persisted pipeline state document."""
    existing_state = db.app.get_pipeline_state(library_id)
    if existing_state is None:
        return 0
    db.app.remove_pipeline_state(library_id)
    return 1


def get_pipeline_state(db: Database, library_id: str) -> str:
    """Return the current pipeline state key for a library.

    Raises:
        ValueError: If the library has no persisted pipeline state.
    """
    state = db.app.get_pipeline_state(library_id)
    if state is None:
        msg = f"No pipeline state edge found for library {library_id}"
        raise ValueError(msg)
    return state


def get_libraries_in_pipeline_state(db: Database, state: str) -> list[str]:
    """Return library document ids whose current pipeline state matches `state`."""
    libraries = cast("list[dict[str, Any]]", db.library.list_libraries())
    return [
        normalize_library_id(str(doc["_id"]))
        for doc in libraries
        if db.app.get_pipeline_state(normalize_library_id(str(doc["_id"]))) == state
    ]


def bulk_transition_pipeline_state(db: Database, from_state: str, to_state: str) -> int:
    """Transition every library currently in `from_state` to `to_state`."""
    library_ids = get_libraries_in_pipeline_state(db, from_state)
    for library_id in library_ids:
        db.app.update_pipeline_state(library_id, to_state)
    return len(library_ids)


def _get_library_record(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return one library document by `_id` or bare key without scan enrichment."""
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


def _upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[str]:
    """Batch-upsert library files, ownership edges, and initial state edges."""
    if not file_docs:
        return []

    library_ids = [doc.get("library_id") for doc in file_docs]
    clean_docs = [{key: value for key, value in doc.items() if key != "library_id"} for doc in file_docs]

    # Identify which paths already exist before upserting so state edges are
    # only initialised for genuinely new files.  Re-initialising an existing
    # file would silently re-insert the negative-side edges for every axis
    # (e.g. not_tagged), overwriting transitions that have already occurred
    # and pushing those files backwards through the pipeline.
    paths = [d["path"] for d in clean_docs if "path" in d]
    existing_paths = get_existing_file_paths(db, paths)

    library_id = library_ids[0]
    if not isinstance(library_id, str) or not all(lid == library_id for lid in library_ids):
        msg = "All docs in a scan batch must share the same string library_id"
        raise ValueError(msg)

    file_ids = db.library.add_files_to_library(library_id, clean_docs)

    # Repair existing files whose state edges are missing (e.g. interrupted prior scan).
    # Using insert-ignoring semantics means already-transitioned edges are untouched.
    existing_file_ids = [
        file_id for file_id, doc in zip(file_ids, clean_docs, strict=True) if doc.get("path") in existing_paths
    ]
    if existing_file_ids:
        missing_state_ids = [fid for fid in existing_file_ids if db.app.get_file_state(fid) is None]
        if missing_state_ids:
            logger.warning("[scan] Repairing %d file(s) with missing state edges", len(missing_state_ids))
            initialize_file_states_batch(db, missing_state_ids)

    return file_ids


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
    """Return whether the library pipeline is currently in the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        ``True`` when the library pipeline state is ``scanning``; otherwise ``False``.

    """
    try:
        pipeline_state_key = get_pipeline_state(db, library_id)
    except ValueError:
        return False
    return pipeline_state_key == _PIPELINE_SCANNING_KEY


def get_scanning_library_ids(db: Database) -> set[str]:
    """Return the set of library IDs currently in PIPELINE_SCANNING state."""
    return set(get_libraries_in_pipeline_state(db, PIPELINE_SCANNING))


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
            pipeline_state: str | None = get_pipeline_state(db, library_id)
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

    if update_fields:
        update_scan_state(db, library_id, **update_fields)


def transition_to_scanning(db: Database, library_id: str) -> None:
    """Transition a library pipeline into the scanning state.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    transition_pipeline_state(db, library_id, PIPELINE_SCANNING)


def on_scan_complete_pipeline_hook(db: Database, library_id: str) -> None:
    """Transition pipeline state after scan completion based on file count.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    file_count = count_library_files(db, library_id)
    next_state = PIPELINE_ML_RUNNING if file_count > 0 else PIPELINE_IDLE
    transition_pipeline_state(db, library_id, next_state)


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
    files_tuple = list_library_files(db, limit=1_000_000, offset=0)
    existing_files_dict: dict[str, dict[str, Any]] = {f["path"]: f for f in files_tuple[0]}
    has_tagged_files = library_has_tagged_files(db, library_id)
    return existing_files_dict, has_tagged_files


# ---------------------------------------------------------------------------
# Batch file operations
# ---------------------------------------------------------------------------


def upsert_scanned_files(
    db: Database,
    file_entries: list[dict[str, Any]],
    edge_bootstraps: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Batch-upsert scanned file documents and optionally bootstrap state edges.

    Args:
        db: Database instance
        file_entries: File documents to upsert
        edge_bootstraps: Optional edge bootstrap metadata from FileBatchResult.
            If provided, creates ml_tagged state edges for matching files.

    Returns:
        List of document _ids (inserted or updated)

    """
    file_ids = _upsert_batch(db, file_entries)

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
    edge_bootstraps: list[dict[str, Any]],
    file_id_by_path: dict[str, str],
) -> int:
    """Create state edges for files based on scan-time metadata.

    Called after upsert_scanned_files to create ml_tagged state edges
    for files that should skip ML tagging.

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
            transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
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
    file_ids = [
        str(file_doc["_id"])
        for path in paths
        if (file_doc := cast("dict[str, Any] | None", db.library.find_file_by_path_any_library(path))) is not None
    ]
    for file_id in file_ids:
        db.library.remove_file(file_id)

    return len(file_ids)


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------


def get_cached_folders(
    db: Database,
    library_id: str,
) -> dict[str, dict[str, Any]]:
    """Load all cached folder records for a library.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Dict mapping relative folder path → folder record

    """
    folders = cast("list[dict[str, Any]]", db.library.list_folders_for_library(library_id))
    return {str(folder["path"]): folder for folder in folders}


def save_folder_record(
    db: Database,
    library_id: str,
    rel_path: str,
    mtime: int,
    file_count: int,
    existing_folder_id: str | None = None,
) -> None:
    """Upsert a single folder cache record.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        rel_path: Folder path relative to library root (POSIX-style)
        mtime: Folder modification time
        file_count: Number of audio files in the folder
        existing_folder_id: Existing cached folder document ``_id`` when known

    """
    if existing_folder_id is not None:
        db.library.remove_library_folder(library_id, existing_folder_id)

    db.library.add_library_folder(library_id, _folder_doc(library_id, rel_path, mtime, file_count))


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
        cached_folders = get_cached_folders(db, library_id)
        stale_ids = [
            cast("str", folder_doc.get("_id", _folder_doc_id(library_id, rel_path)))
            for rel_path, folder_doc in cached_folders.items()
            if rel_path not in existing_folder_rel_paths
        ]
        if stale_ids:
            for stale_id in stale_ids:
                db.library.remove_library_folder(library_id, stale_id)
    except Exception as e:
        logger.warning("Failed to clean up folder records: %s", e)
