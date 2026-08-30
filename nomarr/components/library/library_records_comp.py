"""Library document composition helpers.

Migrated to the library-domain boundary (P4-S1 of TASK-library-domain-facades-A):
components operate on domain ``Library`` values (natural ``(name, root_path)``
identity) and typed ``LibraryUpdate`` commands. No storage row, dictionary, or
generated library id crosses this component's public surface. The scan/stat
transport projection (``LibraryDict``) is built here FROM domain values
(``Library`` + ``LibraryScan`` + ``LibraryPipelineState``); its wire shape is
unchanged but it no longer carries a storage primary key.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nomarr.components.library.library_scan_state_comp import (
    _pipeline_state_to_scan_status,
    get_pipeline_state,
    get_scan_state,
)
from nomarr.components.library.library_song_query_comp import get_library_counts
from nomarr.components.library.library_song_state_comp import count_untagged_files
from nomarr.helpers.constants.pipeline_states import ML_IN_PROGRESS
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryUpdate
from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

_WATCH_MODES = ("off", "event", "poll")
_FILE_WRITE_MODES = ("none", "minimal", "full")


def _cast_watch_mode(watch_mode: str) -> Literal["off", "event", "poll"]:
    """Cast a validated watch-mode string to the ``Library`` literal."""
    return cast("Literal['off', 'event', 'poll']", watch_mode)


def _cast_file_write_mode(file_write_mode: str) -> Literal["none", "minimal", "full"]:
    """Cast a validated file-write-mode string to the ``Library`` literal."""
    return cast("Literal['none', 'minimal', 'full']", file_write_mode)


def create_library_record(
    db: Database,
    *,
    name: str,
    root_path: str,
    is_enabled: bool = True,
    watch_mode: str = "off",
    file_write_mode: str = "full",
    library_auto_write: bool = False,
) -> Library:
    """Insert a library and return the persisted domain ``Library``.

    Raises ValueError if watch_mode or file_write_mode is invalid. Validation is
    delegated to ``LibraryUpdate`` (which enforces the same literals as the
    removed ``_validate_watch_mode``/``_validate_file_write_mode`` helpers).
    """
    LibraryUpdate(
        watch_mode=_cast_watch_mode(watch_mode),
        file_write_mode=_cast_file_write_mode(file_write_mode),
    )
    library = Library(
        name=name,
        root_path=root_path,
        is_enabled=is_enabled,
        watch_mode=_cast_watch_mode(watch_mode),
        file_write_mode=_cast_file_write_mode(file_write_mode),
        library_auto_write=library_auto_write,
    )
    return db.library.create_library(library)


def get_library_record(
    db: Database,
    library: Library,
    *,
    include_scan: bool = True,
) -> Library | None:
    """Get one library by its natural ``(name, root_path)`` identity.

    Returns the domain ``Library`` value. ``include_scan`` is retained for
    signature stability but the domain return carries no scan fields — the
    scan/stat transport projection is built separately (see
    ``_project_library_dict``).
    """
    del include_scan
    return db.library.get_library(library)


def get_library_by_name(
    db: Database,
    name: str,
    *,
    include_scan: bool = False,
) -> Library | None:
    """Get one library by its natural name."""
    del include_scan
    return db.library.get_library_by_name(name)


def list_library_records(
    db: Database,
    *,
    enabled_only: bool = False,
    include_scan: bool = True,
) -> list[LibraryDict]:
    """List libraries, projected to the transport ``LibraryDict`` shape.

    ``LibraryDict`` is built from domain ``Library`` values (plus scan/pipeline
    state when ``include_scan``) — no storage row or generated id is used.
    """
    libraries = db.library.list_libraries(enabled_only=enabled_only)
    return [_project_library_dict(db, library, include_scan=include_scan) for library in libraries]


def list_watchable_library_records(db: Database) -> list[LibraryDict]:
    """Return enabled libraries with file watching turned on (as projections)."""
    libraries = db.library.list_libraries(enabled_only=True)
    return [
        _project_library_dict(db, library, include_scan=False)
        for library in libraries
        if library.watch_mode not in (None, "off")
    ]


def update_library_record(
    db: Database,
    library: Library,
    **fields: Any,
) -> None:
    """Update a library's configuration fields through a typed ``LibraryUpdate``.

    ``library`` supplies the natural ``(name, root_path)`` identity; ``fields``
    map to the domain ``LibraryUpdate`` command (mode literals are validated by
    ``LibraryUpdate`` itself).
    """
    changes = LibraryUpdate(
        name=fields.get("name"),
        root_path=fields.get("root_path"),
        is_enabled=fields.get("is_enabled"),
        watch_mode=_cast_watch_mode(fields["watch_mode"]) if fields.get("watch_mode") is not None else None,
        file_write_mode=(
            _cast_file_write_mode(fields["file_write_mode"]) if fields.get("file_write_mode") is not None else None
        ),
        library_auto_write=fields.get("library_auto_write"),
        updated_at=now_ms().value,
    )
    db.library.update_library(library, changes)


def update_library_config_fields(
    db: Database,
    library: Library,
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

    update_library_record(db, library, **update_fields)


def list_all_libraries(db: Database) -> list[Library]:
    """Return all libraries as domain ``Library`` values for bootstrap callers.

    Previously returned generated library primary-key ids (``list_library_keys``);
    the facade now exposes ``Library`` values and no component depends on a
    generated library id (P2-S4).
    """
    return db.library.list_libraries()


def find_library_containing_path(db: Database, file_path: str) -> Library | None:
    """Find the most specific library root containing ``file_path``.

    Returns the domain ``Library`` whose ``root_path`` contains ``file_path``.
    """
    try:
        normalized_path = Path(file_path).resolve()
    except (ValueError, OSError):
        return None

    libraries = db.library.list_libraries(enabled_only=False)
    libraries.sort(key=lambda lib: len(str(lib.root_path)), reverse=True)

    for library in libraries:
        library_root = library.root_path
        try:
            normalized_path.relative_to(Path(library_root).resolve())
            return library
        except ValueError:
            continue  # Path is not under this library root; try the next one

    return None


def find_ml_complete_libraries(db: Database, min_files: int) -> list[dict[str, Any]]:
    """Return ML-running libraries whose file set is fully tagged.

    Each result dict contains the domain ``Library`` value and ``tagged_count``.
    The domain value is retained so downstream pipeline operations can resolve
    the library's complete natural identity (name and root path).
    """
    del min_files
    libraries = db.library.list_libraries()
    counts = get_library_counts(db)
    completed: list[dict[str, Any]] = []

    for library in libraries:
        pipeline_state = db.library.get_pipeline_state(library)
        if pipeline_state.ml_state != ML_IN_PROGRESS:
            continue
        if count_untagged_files(db, library) != 0:
            continue

        tagged_count = counts.get(library.name, {}).get("file_count", 0)
        completed.append({"library": library, "tagged_count": tagged_count})

    return completed


def _project_library_dict(
    db: Database,
    library: Library,
    *,
    include_scan: bool,
) -> LibraryDict:
    """Build the ``LibraryDict`` transport projection from domain values.

    The generated library id does not cross the component boundary, so
    ``LibraryDict.id`` is ``None`` (wire ids live only in the interface layer).
    """
    base: dict[str, Any] = {
        "id": None,
        "name": library.name,
        "root_path": library.root_path,
        "is_enabled": library.is_enabled,
        "watch_mode": library.watch_mode,
        "file_write_mode": library.file_write_mode,
        "library_auto_write": library.library_auto_write,
    }
    if not include_scan:
        return LibraryDict(**base)

    scan_doc = get_scan_state(db, library)
    successful_scan = db.library.get_latest_successful_scan(library)
    try:
        pipeline_state = get_pipeline_state(db, library)
    except ValueError:
        pipeline_state = None

    return LibraryDict(
        **base,
        scan_status=_pipeline_state_to_scan_status(pipeline_state, scan_doc),
        scan_progress=0 if scan_doc is None else scan_doc.files_processed,
        # The newest row may be a failed/interrupted attempt. Keep summary
        # fields sourced from the most recent successful scan instead.
        scan_total=0 if successful_scan is None else successful_scan.files_found,
        scanned_at=None if successful_scan is None else successful_scan.finished_at,
        scan_error=None if scan_doc is None else scan_doc.error,
        last_scan_started_at=None if scan_doc is None else scan_doc.started_at,
        scan_type_in_progress=None if scan_doc is None else scan_doc.scan_type,
        last_scan_at=None if successful_scan is None else successful_scan.finished_at,
    )
