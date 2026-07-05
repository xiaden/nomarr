"""File and folder scan operations: batch upsert, folder cache, deleted-file cleanup, and state bootstrap."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import (
    get_existing_file_paths,
    list_library_files,
)
from nomarr.components.library.library_file_state_comp import (
    initialize_file_states_batch,
    library_has_tagged_files,
    transition_file_state,
)
from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _folder_key(library_id: str, folder_path: str) -> str:
    """Generate the legacy-stable folder ``_key`` from library id and relative path."""
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


def snapshot_existing_files(
    db: Database,
    library_id: str,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Load all existing library files and check for tagged files.

    Returns a snapshot of what the DB knows before scanning.
    """
    files_tuple = list_library_files(db, limit=1_000_000, offset=0)
    existing_files_dict: dict[str, dict[str, Any]] = {f["path"]: f for f in files_tuple[0]}
    has_tagged_files = library_has_tagged_files(db, library_id)
    return existing_files_dict, has_tagged_files


def upsert_scanned_files(
    db: Database,
    file_entries: list[dict[str, Any]],
    edge_bootstraps: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Batch-upsert scanned file documents and optionally bootstrap state edges."""
    file_ids = _upsert_batch(db, file_entries)

    if edge_bootstraps:
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
    """
    count = 0
    for bootstrap in edge_bootstraps:
        normalized_path = bootstrap["normalized_path"]
        file_id = file_id_by_path.get(normalized_path)
        if not file_id:
            continue

        if bootstrap["type"] == "ml_tagged":
            transition_file_state(db, [file_id], STATE_NOT_PROCESSED, STATE_PROCESSED)
            count += 1
    return count


def remove_deleted_files(db: Database, paths: list[str]) -> int:
    """Bulk-delete files that are no longer on disk."""
    file_ids: list[str] = []
    for path in paths:
        file_doc = db.library.find_file_by_path_any_library(path)
        if isinstance(file_doc, dict) and isinstance(file_doc.get("_id"), str):
            file_ids.append(file_doc["_id"])
    for file_id in file_ids:
        db.library.remove_file(file_id)

    return len(file_ids)


def get_cached_folders(
    db: Database,
    library_id: str,
) -> dict[str, dict[str, Any]]:
    """Load all cached folder records for a library."""
    folders = db.library.list_folders_for_library(library_id)
    if not isinstance(folders, list):
        return {}
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

    The key is deterministic from (library_id, rel_path), so upsert replaces
    the old record atomically. The existing_folder_id parameter is retained
    for signature compatibility.
    """
    db.library.add_library_folder(library_id, _folder_doc(library_id, rel_path, mtime, file_count))


def cleanup_stale_folders(
    db: Database,
    library_id: str,
    existing_folder_rel_paths: set[str],
) -> None:
    """Delete folder records that no longer exist on disk. Logs warning on failure."""
    try:
        cached_folders = get_cached_folders(db, library_id)
        stale_ids = [
            str(folder_doc.get("_id") or _folder_doc_id(library_id, rel_path))
            for rel_path, folder_doc in cached_folders.items()
            if rel_path not in existing_folder_rel_paths
        ]
        if stale_ids:
            for stale_id in stale_ids:
                db.library.remove_library_folder(library_id, stale_id)
    except Exception as e:  # Logged best-effort cleanup; failures should not block the scan
        logger.warning("Failed to clean up folder records: %s", e)
