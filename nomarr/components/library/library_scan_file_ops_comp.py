"""File and folder scan operations for library scans.

Extracted from scan_lifecycle_comp — owns file-batch upsert, folder
cache management, deleted-file cleanup, and state bootstrap.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_song_query_comp import (
    get_existing_file_paths,
    list_songs,
)
from nomarr.components.library.library_song_state_comp import (
    initialize_song_states_batch,
    library_has_tagged_files,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.exceptions import DatabaseStateError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Folder key helpers
# ---------------------------------------------------------------------------


def _folder_key(library_id: int, folder_path: str) -> str:
    """Generate the legacy-stable folder ``key`` from library id and relative path."""
    composite = f"{library_id}/{folder_path}"
    return hashlib.md5(composite.encode("utf-8")).hexdigest()


def _folder_doc_id(library_id: int, folder_path: str) -> str:
    """Return the canonical folder document id for a library/path pair."""
    return f"library_folders/{_folder_key(library_id, folder_path)}"


def _folder_doc(
    library_id: int,
    folder_path: str,
    mtime: int,
    file_count: int,
) -> dict[str, Any]:
    """Build the folder-cache document persisted for quick scans."""
    return {
        "key": _folder_key(library_id, folder_path),
        "path": folder_path,
        "mtime": mtime,
        "file_count": file_count,
        "last_scanned_at": now_ms().value,
    }


# ---------------------------------------------------------------------------
# Batch upsert
# ---------------------------------------------------------------------------


def _upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[int]:
    """Batch-upsert library files, ownership edges, and initial state edges."""
    if not file_docs:
        return []

    library_ids = [doc.get("library_id") for doc in file_docs]
    clean_docs = [{key: value for key, value in doc.items() if key != "library_id"} for doc in file_docs]

    # Identify which paths already exist before upserting so state edges are
    # only initialised for genuinely new files.  Re-initialising an existing
    # file would silently re-insert the negative-side edges for every axis
    # (e.g. not_processed), overwriting transitions that have already occurred
    # and pushing those files backwards through the pipeline.
    paths = [d["path"] for d in clean_docs if "path" in d]
    existing_paths = get_existing_file_paths(db, paths)

    library_id = library_ids[0]
    if not isinstance(library_id, int) or not all(lid == library_id for lid in library_ids):
        msg = "All docs in a scan batch must share the same integer library_id"
        raise ValueError(msg)

    file_ids = db.library.add_songs_to_library(library_id, clean_docs)

    # Repair existing files whose state edges are missing (e.g. interrupted prior scan).
    # Using insert-ignoring semantics means already-transitioned edges are untouched.
    existing_file_ids = [
        file_id for file_id, doc in zip(file_ids, clean_docs, strict=True) if doc.get("path") in existing_paths
    ]
    if existing_file_ids:
        missing_state_ids = [fid for fid in existing_file_ids if not db.app.get_song_states(fid)]
        if missing_state_ids:
            logger.warning("[scan] Repairing %d file(s) with missing state edges", len(missing_state_ids))
            initialize_song_states_batch(db, missing_state_ids)

    return file_ids


# ---------------------------------------------------------------------------
# File snapshots
# ---------------------------------------------------------------------------


def snapshot_existing_files(
    db: Database,
    library_id: int,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Load all existing library files and check for tagged files.

    Returns (existing_files_dict, has_tagged_files).
    """
    files_tuple = list_songs(db, limit=1_000_000, offset=0)
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
) -> list[int]:
    """Batch-upsert scanned files and optionally bootstrap state edges."""
    file_ids = _upsert_batch(db, file_entries)

    if edge_bootstraps:
        # Build path to id map from results
        file_id_by_path: dict[str, int] = {}
        for fid, entry in zip(file_ids, file_entries, strict=True):
            normalized = entry.get("normalized_path")
            if normalized:
                file_id_by_path[normalized] = fid

        bootstrap_file_state_edges(db, edge_bootstraps, file_id_by_path)

    return file_ids


def bootstrap_file_state_edges(
    db: Database,
    edge_bootstraps: list[dict[str, Any]],
    file_id_by_path: dict[str, int],
) -> int:
    """Create ml_tagged state edges for songs that should skip ML tagging.

    Returns the number of edges created.
    """
    count = 0
    for bootstrap in edge_bootstraps:
        normalized_path = bootstrap["normalized_path"]
        file_id = file_id_by_path.get(normalized_path)
        if not file_id:
            continue

        if bootstrap["type"] == "ml_tagged":
            transition_song_state(db, [file_id], STATE_NOT_PROCESSED, STATE_PROCESSED)
            count += 1
    return count


def remove_deleted_files(db: Database, library_id: int, paths: list[str]) -> int:
    """Bulk-delete files that are no longer on disk.

    Paths are resolved within the scanning library.  Relative paths can be
    shared by multiple libraries, so an unscoped lookup could delete another
    library's song.

    Returns the number of files deleted.
    """
    file_ids = [
        file_doc["id"]
        for path in paths
        if (file_doc := cast("dict[str, Any] | None", db.library.get_song_by_path(path, library_id))) is not None
    ]
    for file_id in file_ids:
        db.library.remove_song(file_id)

    return len(file_ids)


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------


def get_cached_folders(
    db: Database,
    library_id: int,
) -> dict[str, dict[str, Any]]:
    """Load all cached folder records for a library."""
    folders = cast("list[dict[str, Any]]", db.library.list_folders_for_library(library_id))
    return {str(folder["path"]): folder for folder in folders}


def save_folder_record(
    db: Database,
    library_id: int,
    rel_path: str,
    mtime: int,
    file_count: int,
    existing_folder_id: int | None = None,
) -> None:
    """Upsert a folder cache record (keyed deterministically by library/path)."""
    folder_doc = _folder_doc(library_id, rel_path, mtime, file_count)
    folder_key = folder_doc["key"]

    # Replace in one transaction so a failed insert cannot leave the cache
    # missing after the old record has been deleted.
    if existing_folder_id:
        db.library.replace_library_folder(library_id, existing_folder_id, folder_doc)
    else:
        existing = db.library.list_folders_for_library(library_id)
        for folder in cast("list[dict[str, Any]]", existing):
            if folder.get("key") == folder_key:
                fid = folder.get("id")
                if fid:
                    db.library.replace_library_folder(library_id, fid, folder_doc)
                break
        else:
            db.library.add_library_folder(library_id, folder_doc)


def cleanup_stale_folders(
    db: Database,
    library_id: int,
    existing_folder_rel_paths: set[str],
) -> None:
    """Delete folder cache records that no longer exist on disk."""
    try:
        cached_folders = get_cached_folders(db, library_id)
        stale_ids = [
            cast("int", folder_doc["id"])
            for rel_path, folder_doc in cached_folders.items()
            if rel_path not in existing_folder_rel_paths
        ]
        if stale_ids:
            for stale_id in stale_ids:
                db.library.remove_library_folder(library_id, stale_id)
    except DatabaseStateError as e:
        logger.warning("[scan] Failed to clean up folder records: %s", e)
