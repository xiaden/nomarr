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
from typing import TYPE_CHECKING, cast

from nomarr.components.library.library_file_query_comp import clear_library_data as clear_library_file_data
from nomarr.components.library.library_id_comp import library_key_from_ref
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
from nomarr.components.library.scan_lifecycle_comp import (
    ensure_scan_state,
    get_scanning_library_ids,
    transition_pipeline_state,
)
from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags
from nomarr.helpers.constants.pipeline_states import PIPELINE_IDLE

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
    """Create a new library with validation and name generation.

    Args:
        db: Database instance
        base_library_root: Base library root from config (security boundary)
        name: Library name (optional: auto-generated from path basename)
        root_path: Path to library root (must be within base_library_root)
        is_enabled: Whether library is enabled for scanning
        watch_mode: File watching mode ('off', 'event', or 'poll')
        file_write_mode: Tag write mode ('none', 'minimal', or 'full')
        library_auto_write: Whether to enable automatic tag writing for the library.

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
            ),
        )
        transition_pipeline_state(db, library_id, PIPELINE_IDLE)
        ensure_scan_state(db, library_id)
    except Exception as e:
        msg = f"Failed to create library: {e}"
        raise ValueError(msg) from e
    logger.info(f"[LibraryAdmin] Created library: {resolved_name} at {abs_path}")
    return library_id


def update_library_root(db: Database, base_library_root: str | None, library_id: str, root_path: str) -> None:
    """Update a library's root path with validation.

    Args:
        db: Database instance
        base_library_root: Base library root from config (security boundary)
        library_id: Library ID to update
        root_path: New path to library root

    Raises:
        ValueError: If library not found or path is invalid

    """
    library = get_library_record(db, library_id)
    if not library:
        msg = f"Library not found: {library_id}"
        raise ValueError(msg)
    base_root = get_base_library_root(base_library_root)
    abs_path = normalize_library_root(base_root, root_path)
    ensure_no_overlapping_library_root(db, abs_path, ignore_id=library_id)
    update_library_record(db, library_id, root_path=abs_path)
    logger.info(f"[LibraryAdmin] Updated library {library_id} root path to {abs_path}")


_BATCH_SIZE = 500


def delete_library(db: Database, library_id: str) -> bool:
    """Delete a library and all associated data in batched Python-orchestrated steps.

    Uses sequential small AQL queries rather than a single large cascade to
    avoid timeouts on libraries with many files.

    Args:
        db: Database instance
        library_id: Library ID to delete

    Returns:
        True if deleted, False if not found

    """
    library = get_library_record(db, library_id)
    if not library:
        return False

    lib_key = library_key_from_ref(library_id)
    library_full_id = f"libraries/{lib_key}"

    # Collect all file IDs for this library upfront.
    file_docs = cast("list[dict]", db.libraries.library_contains_file(library_full_id, limit=None))
    file_ids = [doc["_id"] for doc in file_docs if isinstance(doc.get("_id"), str)]

    # Delete per-file derived data in batches.
    from nomarr.components.ml.inference.ml_output_stream_store_comp import delete_output_streams

    for i in range(0, max(len(file_ids), 1), _BATCH_SIZE):
        batch = file_ids[i : i + _BATCH_SIZE]
        if not batch:
            break
        # Delete canonical output streams before removing the file-side edges.
        for file_id in batch:
            delete_output_streams(db, file_id)
        # Delete per-file edge collections.
        db.file_has_state.delete.in_(_from=batch)
        db.file_has_vectors.delete.in_(_from=batch)
        db.song_has_tags.delete.in_(_from=batch)
        db.worker_claims.delete.in_(file_id=batch)

    # Delete orphan tags after clearing song_has_tags edges.
    # The cleanup component also checks tag_model_output edges so tags still
    # referenced by ML model outputs are preserved.
    cleanup_orphaned_tags(db)

    # Delete vector template collections scoped to this library.
    for coll_name, coll in list(db._registered.items()):
        if coll_name.endswith(f"__{lib_key}"):
            coll.truncate()

    # Delete library-scoped edge collections (single query each).
    db.library_contains_file.delete(_from=library_full_id)
    db.library_contains_folder.delete(_from=library_full_id)
    db.library_has_scan.delete(_from=library_full_id)
    db.library_has_pipeline_state.delete(_from=library_full_id)

    # Delete library-scoped document collections (single AQL each via library_key field).
    db.library_files.delete(library_key=lib_key)
    db.library_folders.delete(library_key=lib_key)
    db.library_scans.delete(library_key=lib_key)
    db.library_pipeline_states.delete(library_key=lib_key)

    # Finally, delete the library document itself.
    db.libraries.delete(_key=lib_key)

    logger.info(f"[LibraryAdmin] Deleted library {library_id}: {library.get('name')} ({len(file_ids)} files removed)")
    return True


def clear_library_data(db: Database, library_root: str | None) -> None:
    """Clear all library data with precondition checks.

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
