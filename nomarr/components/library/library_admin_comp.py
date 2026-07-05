"""Library administration: create, update, delete, and clear library data with validation."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, cast

from nomarr.components.library.library_file_query_comp import clear_library_data as clear_library_file_data
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
from nomarr.components.library.library_scan_state_comp import ensure_scan_state
from nomarr.components.library.scan_lifecycle_comp import get_scanning_library_ids
from nomarr.helpers.constants.pipeline_states import PIPELINE_DEFAULTS

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
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
) -> str:
    """Create a new library with validation and name generation."""
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore_id=None)
    resolved_name = _resolve_library_name(db, name, abs_path)
    try:
        library_id = cast(
            "str",
            create_library_record(
                db,
                name=resolved_name,
                root_path=abs_path,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
                **PIPELINE_DEFAULTS,
            ),
        )
        ensure_scan_state(db, library_id)
    except (ValueError, RuntimeError, OSError) as e:
        msg = f"Failed to create library: {e}"
        raise ValueError(msg) from e
    logger.info("[LibraryAdmin] Created library: %s at %s", resolved_name, abs_path)
    return library_id


def update_library_root(db: Database, base_library_root: str | None, library_id: str, root_path: str) -> None:
    """Update a library's root path with validation."""
    library = get_library_record(db, library_id)
    if not library:
        msg = f"Library not found: {library_id}"
        raise ValueError(msg)
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore_id=library_id)
    update_library_record(db, library_id, root_path=abs_path)
    logger.info("[LibraryAdmin] Updated library %s root path to %s", library_id, abs_path)


_BATCH_SIZE = 500


def delete_library(db: Database, library_id: str) -> bool:
    """Delete a library and all associated data. Returns True if deleted, False if not found."""
    library = get_library_record(db, library_id)
    if not library:
        return False

    db.library.remove_library(library_id)
    logger.info("[LibraryAdmin] Deleted library %s: %s", library_id, library.get("name"))
    return True


def clear_library_data(db: Database, library_root: str | None) -> None:
    """Clear all library data. Requires configured library_root and no running scan jobs.

    Raises ValueError if library_root not configured, RuntimeError if scan jobs are running.
    """
    if not library_root:
        msg = "Library root not configured"
        raise ValueError(msg)
    if _is_scan_running(db):
        msg = "Cannot clear library while scan jobs are running. Cancel scans first."
        raise RuntimeError(msg)
    clear_library_file_data(db)
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
    """Check if any library pipeline is currently in the scanning state."""
    scanning_libraries = get_scanning_library_ids(db)
    return len(scanning_libraries) > 0
