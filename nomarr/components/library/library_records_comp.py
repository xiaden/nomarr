"""Library document composition helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_scan_state_comp import (
    _pipeline_state_to_scan_status,
    get_pipeline_state,
    get_scan_state,
)
from nomarr.components.library.library_song_query_comp import get_library_counts
from nomarr.components.library.library_song_state_comp import count_untagged_files
from nomarr.helpers.constants.pipeline_states import ML_IN_PROGRESS
from nomarr.helpers.dto.library_dto import LibraryDict
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
) -> int:
    """Insert a library document.

    Raises ValueError if watch_mode or file_write_mode is invalid.
    """
    _validate_watch_mode(watch_mode)
    _validate_file_write_mode(file_write_mode)

    timestamp = now_ms().value
    result = db.library.add_library(
        {
            "name": name,
            "root_path": root_path,
            "is_enabled": is_enabled,
            "watch_mode": watch_mode,
            "file_write_mode": file_write_mode,
            "library_auto_write": library_auto_write,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )
    return cast("int", result)


def get_library_record(
    db: Database,
    library_id: int,
    *,
    include_scan: bool = True,
) -> dict[str, Any] | None:
    """Get one library by ``id`` and optionally merge scan state."""
    row = cast("dict[str, Any] | None", db.library.get_library(library_id))
    doc = None if row is None else _row_to_library_doc(row)

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
    row = cast("dict[str, Any] | None", db.library.get_library_by_name(name))
    doc = None if row is None else _row_to_library_doc(row)
    if doc is None or not include_scan:
        return doc
    return _merge_scan_state(db, doc)


def list_library_records(
    db: Database,
    *,
    enabled_only: bool = False,
    include_scan: bool = True,
) -> list[LibraryDict]:
    """List libraries through constructor verbs, preserving legacy sort order."""
    docs = cast(
        "list[dict[str, Any]]",
        db.library.list_libraries(enabled_only=enabled_only),
    )
    docs = [_row_to_library_doc(doc) for doc in docs]
    if include_scan:
        docs = [_merge_scan_state(db, doc) for doc in docs]
    return [LibraryDict(**doc) for doc in docs]


def list_watchable_library_records(db: Database) -> list[LibraryDict]:
    """Return enabled libraries with file watching turned on."""
    libraries = list_library_records(db, enabled_only=True, include_scan=False)
    return [lib for lib in libraries if lib.watch_mode not in (None, "off")]


def update_library_record(
    db: Database,
    library_id: int,
    **fields: Any,
) -> None:
    """Update a library document by ``id`` through the constructor namespace."""
    update_fields: dict[str, Any] = {"updated_at": now_ms().value}

    # The component API uses intent names, while the repository accepts only
    # columns from the libraries table.
    column_fields = {
        "name": "name",
        "root_path": "path",
        "is_enabled": "library_type",
        "watch_mode": "auto_tag",
        "library_auto_write": "auto_curate",
    }
    for intent_name, column_name in column_fields.items():
        value = fields.get(intent_name)
        if value is None:
            continue
        if intent_name == "is_enabled":
            value = "music" if value else "disabled"
        elif intent_name == "watch_mode":
            value = int(value != "off")
        elif intent_name == "library_auto_write":
            value = int(value)
        update_fields[column_name] = value

    if "watch_mode" in fields and fields["watch_mode"] is not None:
        _validate_watch_mode(cast("str", fields["watch_mode"]))
    if "file_write_mode" in fields and fields["file_write_mode"] is not None:
        _validate_file_write_mode(cast("str", fields["file_write_mode"]))

    # Send all changes through one repository transaction.  The old per-field
    # calls committed independently, so a later failure could leave a library
    # only partially updated.
    db.library.update_library(library_id, update_fields)


def update_library_config_fields(
    db: Database,
    library_id: int,
    set_fields: dict[str, Any] | None = None,
    unset_fields: list[str] | None = None,
) -> None:
    """Update optional library config fields via set/unset semantics.

    Missing and None values are treated equivalently for inheritance.
    """
    update_fields: dict[str, Any] = {}
    if set_fields:
        update_fields.update(set_fields)
    if unset_fields:
        update_fields.update(dict.fromkeys(unset_fields))

    if not update_fields:
        return

    update_library_record(db, library_id, **update_fields)


def list_all_library_keys(db: Database) -> list[int]:
    """Return all library document keys for bootstrap-style callers."""
    return db.library.list_library_keys()


def find_library_containing_path(db: Database, file_path: str) -> LibraryDict | None:
    """Find the most specific library root containing ``file_path``."""
    try:
        normalized_path = Path(file_path).resolve()
    except (ValueError, OSError):
        return None

    libraries = list_library_records(db, enabled_only=False, include_scan=False)
    libraries.sort(key=lambda lib: len(str(lib.root_path)), reverse=True)

    for library in libraries:
        library_root = library.root_path
        if not isinstance(library_root, str):
            continue
        try:
            normalized_path.relative_to(Path(library_root).resolve())
            return library
        except ValueError:
            continue  # Path is not under this library root; try the next one

    return None


def _row_to_library_doc(row: dict[str, Any]) -> dict[str, Any]:
    """Translate repository column names into the library intent shape.

    The repository returns ``LibraryRow`` keys, while callers consume the
    public ``LibraryDict`` vocabulary.  Keep this boundary explicit and omit
    persistence-only columns rather than passing them to the DTO constructor.
    """
    if "path" in row:
        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "root_path": row["path"],
            "is_enabled": row.get("library_type") != "disabled",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "watch_mode": "event" if row.get("auto_tag") else "off",
            "library_auto_write": bool(row.get("auto_curate")),
            "file_write_mode": "full",
        }

    # Accept already-projected records from component-level test doubles and
    # legacy callers while still dropping unknown keys before LibraryDict.
    allowed = {
        "id",
        "name",
        "root_path",
        "is_enabled",
        "created_at",
        "updated_at",
        "watch_mode",
        "file_write_mode",
        "library_auto_write",
        "scan_status",
        "scan_progress",
        "scan_total",
        "scanned_at",
        "scan_error",
        "last_scan_started_at",
        "last_scan_at",
        "scan_type_in_progress",
        "scan_state",
        "ml_state",
        "calibration_state",
        "tag_write_state",
        "vector_search_thoroughness",
        "vector_group_size",
        "file_count",
        "folder_count",
    }
    return {key: value for key, value in row.items() if key in allowed}


def find_ml_complete_libraries(db: Database, min_files: int) -> list[dict[str, Any]]:
    """Return ML-running libraries whose file set is fully tagged.

    Each result dict contains ``library_id`` and ``tagged_count``.
    """
    del min_files
    library_docs = cast("list[dict[str, Any]]", db.library.list_libraries())
    counts = get_library_counts(db)
    completed: list[dict[str, Any]] = []

    for library_doc in library_docs:
        library_ref = library_doc.get("id")
        if not isinstance(library_ref, int):
            continue
        library_id = library_ref
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
    library_id = library["id"]
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
