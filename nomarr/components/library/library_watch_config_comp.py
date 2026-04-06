"""Library watch configuration component."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def list_watchable_libraries(db: Database) -> list[dict[str, Any]]:
    """Return libraries eligible for file watching.

    Projects persistence results to the bounded watcher contract:
    ``{"_id", "root_path", "watch_mode"}``.

    Args:
        db: Database connection.

    Returns:
        Watchable library documents with only watcher-relevant fields.

    """
    libraries = db.libraries.list_watchable_libraries()
    return [_project_watchable_library(library) for library in libraries]


def get_library_watch_config(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return watch configuration for a single library.

    Args:
        db: Database connection.
        library_id: Library document ``_id``.

    Returns:
        Projected watch configuration with ``root_path``, ``watch_mode``, and
        ``is_enabled``, or ``None`` when the library does not exist.

    """
    library = db.libraries.get_library(library_id)
    if library is None:
        return None

    return {
        "root_path": library.get("root_path"),
        "watch_mode": library.get("watch_mode"),
        "is_enabled": library.get("is_enabled"),
    }


def _project_watchable_library(library: dict[str, Any]) -> dict[str, Any]:
    """Project a library doc to the watcher list contract."""
    return {
        "_id": library.get("_id"),
        "root_path": library.get("root_path"),
        "watch_mode": library.get("watch_mode"),
    }
