"""Library watch configuration component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_records_comp import get_library_record, list_watchable_library_records

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto.library_dto import LibraryDict
    from nomarr.persistence.db import Database


def list_watchable_libraries(db: Database) -> list[dict[str, Any]]:
    """Return libraries eligible for file watching.

    Projects to ``{"id", "root_path", "watch_mode"}`` — ``id`` is the library's
    natural ``name`` (no generated primary key crosses the component boundary).
    """
    libraries = list_watchable_library_records(db)
    return [_project_watchable_library(library) for library in libraries]


def get_library_watch_config(db: Database, library: Library) -> dict[str, Any] | None:
    """Return watch config for a library, or None if not found.

    Returns ``{"root_path", "watch_mode", "is_enabled"}``.
    """
    resolved = get_library_record(db, library, include_scan=False)
    if resolved is None:
        return None
    return {
        "root_path": resolved.root_path,
        "watch_mode": resolved.watch_mode,
        "is_enabled": resolved.is_enabled,
    }


def _project_watchable_library(library: LibraryDict) -> dict[str, Any]:
    """Project a LibraryDict to the watcher list contract."""
    return {
        "id": library.name,
        "root_path": library.root_path,
        "watch_mode": library.watch_mode,
    }
