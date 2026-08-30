"""Library administration: create, update, delete, and clear libraries."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import (
    create_library_record,
    get_library_by_name,
    get_library_record,
    update_library_record,
)
from nomarr.components.library.library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
)
from nomarr.components.library.library_scan_state_comp import get_libraries_in_axis_state
from nomarr.components.library.library_song_query_comp import clear_library_data as clear_library_song_data
from nomarr.helpers.constants.pipeline_states import SCAN_IN_PROGRESS, SCAN_STATE_FIELD
from nomarr.helpers.exceptions import DatabaseStateError, DuplicateEntityError

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


def create_library(
    db: Database,
    base_library_root: str | None,
    name: str | None,
    root_path: str,
    is_enabled: bool = True,
    watch_mode: str = "off",
    file_write_mode: str = "full",
    library_auto_write: bool = False,
) -> Library:
    """Create a new library and return the persisted domain ``Library``.

    Raises ValueError if the name already exists or the path is invalid.
    """
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path)
    resolved_name = _resolve_library_name(db, name, abs_path)
    try:
        return create_library_record(
            db,
            name=resolved_name,
            root_path=abs_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )
    except DuplicateEntityError as e:
        # The pre-check above is not atomic; the database UNIQUE constraint on
        # ``libraries.name`` is the authority. Surface the concurrent-create race
        # as the same friendly error a pre-check collision produces.
        raise ValueError(f"Library name already exists: {resolved_name}") from e
    except (ValueError, DatabaseStateError, OSError) as e:
        msg = f"Failed to create library: {e}"
        raise ValueError(msg) from e


def resolve_library_root(db: Database, base_library_root: str | None, library: Library, root_path: str) -> str:
    """Validate and normalize a library root without persisting it."""
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore=library)
    return abs_path


def update_library_root(db: Database, base_library_root: str | None, library: Library, root_path: str) -> None:
    """Update a library's root path.

    Raises ValueError if the library is not found or the path is invalid.
    """
    abs_path = resolve_library_root(db, base_library_root, library, root_path)
    update_library_record(db, library, root_path=abs_path)
    logger.info(f"[LibraryAdmin] Updated library {library.name} root path to {abs_path}")


def delete_library(db: Database, library: Library) -> bool:
    """Delete a library and all associated data.

    Returns True if deleted, False if not found.
    """
    existing = get_library_record(db, library)
    if not existing:
        return False

    db.library.remove_library(existing)
    logger.info(f"[LibraryAdmin] Deleted library {existing.name}")
    return True


def clear_library_data(db: Database, library_root: str | None) -> None:
    """Clear all library data.

    Raises ValueError if library_root is not configured,
    RuntimeError if scan jobs are running.
    """
    if not library_root:
        msg = "Library root not configured"
        raise ValueError(msg)
    if _is_scan_running(db):
        msg = "Cannot clear library while scan jobs are running. Cancel scans first."
        raise RuntimeError(msg)
    clear_library_song_data(db)
    logger.info("[LibraryAdmin] Library data cleared")


def _resolve_library_name(db: Database, name: str | None, abs_path: str) -> str:
    """Resolve library name - generate from path or validate uniqueness."""
    if not name or not name.strip():
        generated_name = os.path.basename(abs_path.rstrip(os.sep)) or "Library"
        base_name = generated_name
        counter = 1
        while get_library_by_name(db, generated_name):
            counter += 1
            generated_name = f"{base_name} ({counter})"
        return generated_name
    existing = get_library_by_name(db, name)
    if existing:
        msg = f"Library name already exists: {name}"
        raise ValueError(msg)
    return name


def _is_scan_running(db: Database) -> bool:
    """Return True if any library pipeline is currently scanning."""
    scanning_libraries = get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
    return len(scanning_libraries) > 0
