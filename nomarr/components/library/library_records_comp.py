"""Constructor-backed helpers for library documents.

This module owns light composition logic that is not itself a constructor
verb: scan-state enrichment, filesystem path ownership checks, bootstrap
key enumeration, and ML-complete library discovery.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_query_comp import get_library_counts
from nomarr.components.library.library_file_state_comp import count_untagged_files
from nomarr.components.library.scan_lifecycle_comp import (
    _pipeline_state_to_scan_status,
    get_pipeline_state,
    get_scan_state,
)
from nomarr.helpers.constants.pipeline_states import PIPELINE_ML_RUNNING
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike
    from nomarr.persistence.db import Database


def normalize_library_id(library_id: str) -> str:
    """Normalize a library reference to a full ``libraries/{key}`` id."""
    if library_id.startswith("libraries/"):
        return library_id
    return f"libraries/{library_id}"


def library_key_from_ref(library_id: str) -> str:
    """Extract the library ``_key`` from either a full id or a bare key."""
    if library_id.startswith("libraries/"):
        return library_id.split("/", 1)[1]
    return library_id


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
    """Insert a library document through the constructor namespace.

    Args:
        db: Database handle used to insert the library document.
        name: Human-readable library name.
        root_path: Absolute root path scanned for this library.
        is_enabled: Whether the library is enabled for processing; defaults to ``True``.
        watch_mode: File watching mode; defaults to ``"off"`` and must be one of ``"off"``, ``"event"``, or ``"poll"``.
        file_write_mode: Tag writeback mode; defaults to ``"full"`` and must be one of ``"none"``, ``"minimal"``, or ``"full"``.
        library_auto_write: Whether library-level automatic tag writing is enabled; defaults to ``False``.

    Returns:
        The ``_id`` string of the created library document.

    Raises:
        ValueError: If ``watch_mode`` or ``file_write_mode`` is not a valid value.
    """
    _validate_watch_mode(watch_mode)
    _validate_file_write_mode(file_write_mode)

    timestamp = now_ms().value
    return db.libraries.insert(
        [
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
        ]
    )[0]


def get_library_record(
    db: Database,
    library_id: str,
    *,
    include_scan: bool = True,
) -> dict[str, Any] | None:
    """Get one library by ``_id`` or ``_key`` and optionally merge scan state."""
    if library_id.startswith("libraries/"):
        doc = cast("dict[str, Any] | None", db.libraries.get(library_id))
    else:
        doc = cast("dict[str, Any] | None", db.libraries._key.get(library_id))

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
    doc = cast("dict[str, Any] | None", db.libraries.name.get(name))
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
    if enabled_only:
        docs = cast(
            "list[dict[str, Any]]",
            db.libraries.is_enabled.get(True),
        )
    else:
        ids = cast("list[str]", db.libraries._id.collect(limit=db.libraries.count()))
        docs = [doc for doc_id in ids if (doc := cast("dict[str, Any] | None", db.libraries.get(doc_id))) is not None]

    docs.sort(key=lambda doc: int(cast("int", doc.get("created_at", 0) or 0)))
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
    **fields: Any,
) -> None:
    """Update a library document by ``_id`` through the constructor namespace."""
    update_fields = {
        "updated_at": now_ms().value,
        **{key: value for key, value in fields.items() if value is not None},
    }

    if "watch_mode" in fields and fields["watch_mode"] is not None:
        _validate_watch_mode(cast("str", fields["watch_mode"]))
    if "file_write_mode" in fields and fields["file_write_mode"] is not None:
        _validate_file_write_mode(cast("str", fields["file_write_mode"]))

    db.libraries._id.update(normalize_library_id(library_id), update_fields)


def update_library_config_fields(
    db: Database,
    library_id: str,
    set_fields: dict[str, Any] | None = None,
    unset_fields: list[str] | None = None,
) -> None:
    """Update optional library config fields.

    Constructor ``update`` does not expose Arango's ``keepNull: false`` toggle,
    so clearing an override persists ``null``. Callers should treat missing and
    ``None`` values equivalently for inheritance.
    """
    update_fields: dict[str, Any] = {}
    if set_fields:
        update_fields.update(set_fields)
    if unset_fields:
        update_fields.update(dict.fromkeys(unset_fields))

    if not update_fields:
        return

    update_library_record(db, library_id, **update_fields)


def list_all_library_keys(db: DatabaseLike) -> list[str]:
    """Return all library document keys for bootstrap-style callers."""
    libraries: Any = getattr(db, "libraries", None)
    if libraries is None:
        libraries = cast(
            "Any", SchemaConstructor(cast("Any", db)).build_collection_namespace("libraries", SCHEMA["libraries"])
        )
    total = int(libraries.count())
    return [str(key) for key in libraries._key.collect(limit=total)]


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
            continue

    return None


def find_ml_complete_libraries(db: Database, min_files: int) -> list[dict[str, Any]]:
    """Find ML-running libraries whose file set is fully tagged.

    Args:
        db: Database handle used to read pipeline state and tagged file counts.
        min_files: Unused minimum file-count threshold accepted for interface
            compatibility; it currently has no effect on the returned results.

    Returns:
        A list of dictionaries for ML-running libraries with no untagged files,
        where each dictionary contains ``library_id`` and ``tagged_count``.
    """
    del min_files
    state_docs = cast(
        "list[dict[str, Any]]",
        db.library_pipeline_states.pipeline_state.get.many(
            PIPELINE_ML_RUNNING,
            limit=db.library_pipeline_states.count(),
        ),
    )
    counts = get_library_counts(db)
    completed: list[dict[str, Any]] = []

    for state_doc in state_docs:
        library_key = str(state_doc["library_key"])
        library_id = normalize_library_id(library_key)
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
