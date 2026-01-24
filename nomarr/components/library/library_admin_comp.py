"""Library administration operations.

This component handles library CRUD operations with validation:
- Create library with path validation and name generation
- Update library root with path validation
- Delete library with policy checks
- Clear library data with precondition checks
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from nomarr.components.library.library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def create_library(
    db: Database,
    base_library_root: str | None,
    name: str | None,
    root_path: str,
    is_enabled: bool = True,
    is_default: bool = False,
    watch_mode: str = "off",
) -> str:
    """
    Create a new library with validation and name generation.

    Args:
        db: Database instance
        base_library_root: Base library root from config (security boundary)
        name: Library name (optional: auto-generated from path basename)
        root_path: Path to library root (must be within base_library_root)
        is_enabled: Whether library is enabled for scanning
        is_default: Whether this is the default library
        watch_mode: File watching mode ('off', 'event', or 'poll')

    Returns:
        Created library ID

    Raises:
        ValueError: If name already exists or path is invalid
    """
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore_id=None)

    resolved_name = _resolve_library_name(db, name, abs_path)

    try:
        library_id = db.libraries.create_library(
            name=resolved_name,
            root_path=abs_path,
            is_enabled=is_enabled,
            is_default=is_default,
            watch_mode=watch_mode,
        )
    except Exception as e:
        raise ValueError(f"Failed to create library: {e}") from e

    logging.info(f"[LibraryAdmin] Created library: {resolved_name} at {abs_path}")
    return library_id


def update_library_root(
    db: Database,
    base_library_root: str | None,
    library_id: str,
    root_path: str,
) -> None:
    """
    Update a library's root path with validation.

    Args:
        db: Database instance
        base_library_root: Base library root from config (security boundary)
        library_id: Library ID to update
        root_path: New path to library root

    Raises:
        ValueError: If library not found or path is invalid
    """
    library = db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library not found: {library_id}")

    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore_id=library_id)

    db.libraries.update_library(library_id, root_path=abs_path)
    logging.info(f"[LibraryAdmin] Updated library {library_id} root path to {abs_path}")


def delete_library(db: Database, library_id: str) -> bool:
    """
    Delete a library.

    Args:
        db: Database instance
        library_id: Library ID to delete

    Returns:
        True if deleted, False if not found
    """
    library = db.libraries.get_library(library_id)
    if not library:
        return False

    db.libraries.delete_library(library_id)
    logging.info(f"[LibraryAdmin] Deleted library {library_id}: {library.get('name')}")
    return True


def clear_library_data(db: Database, library_root: str | None) -> None:
    """
    Clear all library data with precondition checks.

    Preconditions:
    - library_root must be configured
    - No scan jobs can be running

    Args:
        db: Database instance
        library_root: Library root from config

    Raises:
        ValueError: If library_root not configured
        RuntimeError: If scan jobs are running
    """
    if not library_root:
        raise ValueError("Library root not configured")

    if _is_scan_running(db):
        raise RuntimeError("Cannot clear library while scan jobs are running. Cancel scans first.")

    db.library_files.clear_library_data()
    logging.info("[LibraryAdmin] Library data cleared")


def _resolve_library_name(db: Database, name: str | None, abs_path: str) -> str:
    """Resolve library name - generate from path or validate uniqueness."""
    if not name or not name.strip():
        generated_name = os.path.basename(abs_path.rstrip(os.sep)) or "Library"
        base_name = generated_name
        counter = 1
        while db.libraries.get_library_by_name(generated_name):
            counter += 1
            generated_name = f"{base_name} ({counter})"
        return generated_name

    existing = db.libraries.get_library_by_name(name)
    if existing:
        raise ValueError(f"Library name already exists: {name}")
    return name


def _is_scan_running(db: Database) -> bool:
    """Check if any library has an active scan."""
    libraries = db.libraries.list_libraries(enabled_only=False)
    return any(lib.get("scan_status") == "scanning" for lib in libraries)
