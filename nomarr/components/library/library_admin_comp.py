"""Library administration: create, update, delete, and clear libraries."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

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
from nomarr.components.library.library_scan_state_comp import (
    ensure_scan_state,
    get_libraries_in_axis_state,
)
from nomarr.helpers.constants.pipeline_states import PIPELINE_DEFAULTS, SCAN_IN_PROGRESS, SCAN_STATE_FIELD
from nomarr.persistence.exceptions import PersistenceError

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database


async def create_library(
    db: Database,
    base_library_root: str | None,
    name: str | None,
    root_path: str,
    is_enabled: bool = True,
    watch_mode: str = "off",
    file_write_mode: str = "full",
    library_auto_write: bool = False,
) -> int:
    """Create a new library.

    Raises ValueError if the name already exists or the path is invalid.
    """
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    await ensure_no_overlapping_library_root(db, abs_path, ignore_id=None)
    resolved_name = await _resolve_library_name(db, name, abs_path)
    try:
        library_id = await create_library_record(
            db,
            name=resolved_name,
            root_path=abs_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
            **PIPELINE_DEFAULTS,
        )
        await ensure_scan_state(db, library_id)
    except (ValueError, PersistenceError, OSError) as e:
        msg = f"Failed to create library: {e}"
        raise ValueError(msg) from e
    logger.info(f"[LibraryAdmin] Created library: {resolved_name} at {abs_path}")
    return library_id


async def update_library_root(db: Database, base_library_root: str | None, library_id: int, root_path: str) -> None:
    """Update a library's root path.

    Raises ValueError if the library is not found or the path is invalid.
    """
    library = await get_library_record(db, library_id)
    if not library:
        msg = f"Library not found: {library_id}"
        raise ValueError(msg)
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    await ensure_no_overlapping_library_root(db, abs_path, ignore_id=str(library_id))
    await update_library_record(db, library_id, root_path=abs_path)
    logger.info(f"[LibraryAdmin] Updated library {library_id} root path to {abs_path}")


async def delete_library(db: Database, library_id: int) -> bool:
    """Delete a library and all associated data.

    Returns True if deleted, False if not found.
    """
    library = await get_library_record(db, library_id)
    if not library:
        return False

    await db.library.remove_library(library_id)
    logger.info(f"[LibraryAdmin] Deleted library {library_id}: {library.get('name')}")
    return True


async def clear_library_data(db: Database, library_root: str | None) -> None:
    """Clear all library data.

    Raises ValueError if library_root is not configured,
    RuntimeError if scan jobs are running.
    """
    if not library_root:
        msg = "Library root not configured"
        raise ValueError(msg)
    if await _is_scan_running(db):
        msg = "Cannot clear library while scan jobs are running. Cancel scans first."
        raise RuntimeError(msg)
    await clear_library_file_data(db)
    logger.info("[LibraryAdmin] Library data cleared")


async def _resolve_library_name(db: Database, name: str | None, abs_path: str) -> str:
    """Resolve library name - generate from path or validate uniqueness."""
    if not name or not name.strip():
        generated_name = os.path.basename(abs_path.rstrip(os.sep)) or "Library"
        base_name = generated_name
        counter = 1
        while await get_library_by_name(db, generated_name):
            counter += 1
            generated_name = f"{base_name} ({counter})"
        return generated_name
    existing = await get_library_by_name(db, name)
    if existing:
        msg = f"Library name already exists: {name}"
        raise ValueError(msg)
    return name


async def _is_scan_running(db: Database) -> bool:
    """Return True if any library pipeline is currently scanning."""
    scanning_libraries = await get_libraries_in_axis_state(db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
    return len(scanning_libraries) > 0
