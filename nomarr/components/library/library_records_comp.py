"""Constructor-backed helpers for library documents.

This module owns light composition logic that is not itself a constructor
verb: scan-state enrichment, filesystem path ownership checks, bootstrap
key enumeration, and ML-complete library discovery.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import get_library_counts
from nomarr.components.library.library_file_state_comp import count_untagged_files
from nomarr.components.library.library_id_comp import normalize_library_id
from nomarr.components.library.library_scan_state_comp import (
    _pipeline_state_to_scan_status,
    get_pipeline_state,
    get_scan_state,
)
from nomarr.helpers.constants.pipeline_states import ML_IN_PROGRESS
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def create_library_record(
    db: Database,
    *,
    name: str,
    root_path: str,
    is_enabled: bool = True,
    watch_mode: str = "off",
    file_write_mode: str = "full",
    library_auto_write: bool = False,
) -> str:
    """Insert a library document through the constructor namespace."""
    _validate_watch_mode(watch_mode)
    _validate_file_write_mode(file_write_mode)

    timestamp = now_ms().value
    payload = {
        "name": name,
        "root_path": root_path,
        "is_enabled": is_enabled,
        "watch_mode": watch_mode,
        "file_write_mode": file_write_mode,
        "library_auto_write": library_auto_write,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return db.library.add_library(payload)


def get_library_record(
    db: Database,
    library_id: str,
    *,
    include_scan: bool = True,
) -> dict[str, Any] | None:
    """Get one library by ``_id`` or ``_key`` and optionally merge scan state."""
    normalized_library_id = normalize_library_id(library_id)
    doc = db.library.get_library(normalized_library_id)

    if doc is None or not include_scan:
        return doc
    return _merge_scan_state(db, doc)


def get_library_by_name(
    db: Database,
    name: str,
    *,
    include_scan: bool = False,
) -> dict[str, Any] | None:
    """Get one library by unique name."""
    doc = db.library.get_library_by_name(name)
    if doc is None or not include_scan:
        return doc
    return _merge_scan_state(db, doc)


def list_library_records(
    db: Database,
    *,
    enabled_only: bool = False,
    include_scan: bool = True,
) -> list[dict[str, Any]]:
    """List libraries through constructor verbs, preserving legacy sort order."""
    docs = db.library.list_libraries(enabled_only=enabled_only)
    if not isinstance(docs, list):
        return []
    if not include_scan:
        return docs
    return [_merge_scan_state(db, doc) for doc in docs]


def list_watchable_library_records(db: Database) -> list[dict[str, Any]]:
    """Return enabled libraries with file watching turned on."""
    libraries = list_library_records(db, enabled_only=True, include_scan=False)
    return [
        {
            "_id": library.get("_id"),
            "root_path": library.get("root_path"),
            "watch_mode": library.get("watch_mode"),
        }
        for library in libraries
        if library.get("watch_mode") not in (None, "off")
    ]


def update_library_record(
    db: Database,
    library_id: str,
    **fields: str | int | float | bool | None,
) -> None:
    """Update a library document by _id through the constructor namespace."""
    update_fields = {
        "updated_at": now_ms().value,
        **{key: value for key, value in fields.items() if value is not None},
    }

    watch_mode = fields.get("watch_mode")
    if isinstance(watch_mode, str):
        _validate_watch_mode(watch_mode)
    file_write_mode = fields.get("file_write_mode")
    if isinstance(file_write_mode, str):
        _validate_file_write_mode(file_write_mode)

    db.library.update_library(normalize_library_id(library_id), update_fields)


def update_library_config_fields(
    db: Database,
    library_id: str,
    set_fields: dict[str, Any] | None = None,
    unset_fields: list[str] | None = None,
) -> None:
    """Update optional library config fields. None values are treated as missing for inheritance."""
    update_fields: dict[str, Any] = {}
    if set_fields:
        update_fields.update(set_fields)
    if unset_fields:
        update_fields.update(dict.fromkeys(unset_fields))

    if not update_fields:
        return

    update_library_record(db, library_id, **update_fields)


def list_all_library_keys(db: Database) -> list[str]:
    """Return all library document keys for bootstrap-style callers."""
    return db.library.list_library_keys()


def find_library_containing_path(db: Database, file_path: str) -> dict[str, Any] | None:
    """Find the most specific library root containing ``file_path``."""
    try:
        normalized_path = Path(file_path).resolve()
    except (ValueError, OSError):
        return None

    libraries = list_library_records(db, enabled_only=False, include_scan=False)
    libraries.sort(key=lambda doc: len(str(doc.get("root_path", ""))), reverse=True)

    for library in libraries:
        library_root = library.get("root_path")
        if not isinstance(library_root, str):
            continue
        try:
            normalized_path.relative_to(Path(library_root).resolve())
            return library
        except ValueError:
            continue  # Path is not under this library root; try the next one

    return None


def find_ml_complete_libraries(db: Database, min_files: int) -> list[dict[str, Any]]:
    """Find ML-running libraries whose file set is fully tagged.

    The min_files parameter is unused (interface compatibility).
    Returns a list of dicts with library_id and tagged_count.
    """
    del min_files
    library_docs = db.library.list_libraries()
    if not isinstance(library_docs, list):
        return []
    counts = get_library_counts(db)
    completed: list[dict[str, Any]] = []

    for library_doc in library_docs:
        library_ref = library_doc.get("_id") or library_doc.get("_key")
        if not isinstance(library_ref, str):
            continue
        library_id = normalize_library_id(library_ref)
        pipeline_state = db.library.get_pipeline_state(library_id)
        if not pipeline_state or pipeline_state.get("ml_state") != ML_IN_PROGRESS:
            continue
        if count_untagged_files(db, library_id) != 0:
            continue

        tagged_count = counts.get(library_id, {}).get("file_count", 0)
        completed.append({"library_id": library_id, "tagged_count": tagged_count})

    return completed


def _merge_scan_state(db: Database, library: dict[str, Any]) -> dict[str, Any]:
    """Merge library scan state into a library document for API compatibility."""
    library_id = str(library["_id"])
    scan_doc = get_scan_state(db, library_id)
    try:
        pipeline_state = get_pipeline_state(db, library_id)
    except ValueError:
        pipeline_state = None

    return {
        **library,
        "scan_status": _pipeline_state_to_scan_status(pipeline_state, scan_doc),
        "scan_progress": 0 if scan_doc is None else scan_doc.get("files_processed", 0),
        "scan_total": 0 if scan_doc is None else scan_doc.get("files_total", 0),
        "scanned_at": None if scan_doc is None else scan_doc.get("completed_at"),
        "scan_error": None if scan_doc is None else scan_doc.get("error"),
        "last_scan_started_at": None if scan_doc is None else scan_doc.get("started_at"),
        "scan_type_in_progress": None if scan_doc is None else scan_doc.get("scan_type"),
    }


def _validate_watch_mode(watch_mode: str) -> None:
    if watch_mode not in {"off", "event", "poll"}:
        msg = f"Invalid watch_mode: {watch_mode}. Must be 'off', 'event', or 'poll'"
        raise ValueError(msg)


def _validate_file_write_mode(file_write_mode: str) -> None:
    if file_write_mode not in {"none", "minimal", "full"}:
        msg = f"Invalid file_write_mode: {file_write_mode}. Must be 'none', 'minimal', or 'full'"
        raise ValueError(msg)
