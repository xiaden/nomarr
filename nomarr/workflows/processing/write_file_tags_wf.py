"""File tag writing workflow - writes DB tags to audio files.

This workflow writes tags from the database to audio files based on
the library's file_write_mode setting. It handles mode filtering,
calibration requirements, and atomic safe writes.

ARCHITECTURE:
- DB is the source of truth for all tags
- Files are projections controlled per-library
- Mood tags require calibration - filtered out when calibration is empty
- Uses existing TagWriter with atomic safe writes

MODES:
- "none": Remove all nom-style namespaced tags (call TagWriter.write_safe(None))
- "minimal": Only mood-tier tags (mood-strict, mood-regular, mood-loose)
- "full": All available tags from DB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_db
from nomarr.components.library.library_records_comp import find_library_containing_path
from nomarr.components.library.library_song_mutation_comp import update_song_modified_time
from nomarr.components.library.reconciliation_comp import set_file_written
from nomarr.components.processing.file_write_comp import (
    get_file_for_writing,
    get_nomarr_tags,
    release_file_claim,
    resolve_library_root,
)
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tags

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result from write_file_tags_workflow."""

    file_key: str  # Document id of the file
    tags_written: int  # Number of tags written to file
    tags_filtered: int  # Number of tags filtered out by mode
    success: bool  # Whether write succeeded
    error: str | None = None  # Error message if failed


def _filter_tags_for_mode(
    db_tags: Tags | None,
    target_mode: str,
    has_calibration: bool,
) -> Tags | None:
    """Filter tags based on target mode and calibration state.

    Args:
        db_tags: All tags from database (Tags DTO), or ``None`` when no nomarr
            tags exist for the file.
        target_mode: "none", "minimal", or "full"
        has_calibration: Whether calibration exists

    Returns:
        Filtered ``Tags`` for file writing, or ``None`` when nothing should be
        written. ``None`` is the strict representation of "clear/remove all
        tags" — an empty ``Tags`` collection is invalid in the strict model,
        so the empty result is expressed as ``None`` instead.

    """
    # "none" mode clears the namespace entirely.
    if target_mode == "none":
        return None

    # No nomarr tags in DB -> nothing to write; clear to stay consistent.
    if db_tags is None:
        return None

    # Filter out mood tags if uncalibrated (applies to ALL modes)
    if not has_calibration:
        filtered_items = tuple(tag for tag in db_tags.items if not tag.name.startswith("mood-"))
    else:
        filtered_items = db_tags.items  # Already a tuple

    if target_mode == "minimal":
        # Only mood-tier tags
        filtered_items = tuple(tag for tag in filtered_items if tag.name.startswith("mood-"))

    if not filtered_items:
        return None

    # "full" mode - return all tags (already mood-filtered if uncalibrated)
    return Tags(items=filtered_items)


def _resolve_library_path(
    file_doc: dict[str, Any],
    db: Database,
) -> tuple[LibraryPath | None, Library | None]:
    """Resolve ``file_doc`` to a validated ``LibraryPath`` and its domain ``Library``.

    Both the library path and the owning library root are derived from the
    file's physical ``path`` using ``find_library_containing_path`` (path-based
    natural identity), never from the integer storage ``library_id``. Returns
    ``(None, None)`` when no library contains the path, and ``(None, library)``
    when the library is known but the path is otherwise invalid (e.g. missing
    on disk).
    """
    stored_path = file_doc.get("path", "")
    if not stored_path:
        return None, None

    library = find_library_containing_path(db, stored_path)
    if not library:
        return None, None

    library_path = build_library_path_from_db(
        stored_path=stored_path,
        db=db,
        library_id=library.name,
        check_disk=True,
    )

    if not library_path.is_valid():
        return None, library
    return library_path, library


def _release_failed_write(db: Database, file_key: str, worker_id: str) -> None:
    """Release a failed write while leaving it in the reconciliation queue.

    A failed projection write must not be marked current: the database
    projection is still stale and must be retried.  Only the claim is released;
    cleanup is best effort because it runs while handling another failure.
    """
    release_file_claim(db, file_key, worker_id)


def write_file_tags_workflow(
    db: Database,
    file_key: str,
    worker_id: str,
    target_mode: str,
    has_calibration: bool,
    namespace: str = "nom",
) -> WriteResult:
    """Write tags from database to an audio file based on mode.

    This workflow reads tags from the database and writes them to the audio
    file using the appropriate mode filtering. It uses atomic safe writes
    via TagWriter to prevent file corruption.

    Args:
        db: Database instance
        file_key: Document id of the file to write
        target_mode: Desired write mode ("none", "minimal", "full")
        has_calibration: Whether calibration exists (affects mood tag filtering)
        namespace: Tag namespace (default: "nom")

    Returns:
        WriteResult with success status and counts

    Notes:
        - "none" mode clears the namespace entirely
        - "minimal" writes only mood-tier tags
        - "full" writes all DB tags
        - Mood tags are filtered if calibration is empty (any mode)

    """
    try:
        # Get file document via component
        file_id, file_key, file_doc = get_file_for_writing(db, file_key)

        if not file_doc:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"File not found: {file_id}",
            )

        # Resolve library path + owning domain Library from the file's path.
        library_path, library = _resolve_library_path(file_doc, db)
        if not library_path:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Invalid path: {file_doc.get('path')}",
            )

        # Get library root for safe write (domain Library, path-derived).
        if library is None:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Invalid library for path: {file_doc.get('path')}",
            )
        library_root = resolve_library_root(db, library)
        if not library_root:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Library not found: {library.name}",
            )

        # Require known mtime to prevent writing to externally-modified files
        expected_mtime_ms = file_doc.get("modified_time")
        if not isinstance(expected_mtime_ms, int):
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"No valid modified_time in file_doc: {expected_mtime_ms}",
            )

        # Get tags from database (nomarr tags only) - returns Tags | None
        db_tags = get_nomarr_tags(db, file_id)

        # Filter tags for target mode. ``None`` means "clear/remove all tags"
        # and is passed to the writer so it still clears the namespace.
        tags_to_write = _filter_tags_for_mode(db_tags, target_mode, has_calibration)
        tags_filtered = (len(db_tags) if db_tags is not None else 0) - (
            len(tags_to_write) if tags_to_write is not None else 0
        )

        # Create tag writer with overwrite=True to clear namespace first
        tag_writer = TagWriter(overwrite=True, namespace=namespace)

        # Write tags using atomic safe write
        result = tag_writer.write_safe(library_path, tags_to_write, library_root, expected_mtime_ms)
        if not result.success:
            _release_failed_write(db, file_key, worker_id)
            if result.error == "file_modified_externally":
                return WriteResult(
                    file_key=file_key,
                    tags_written=0,
                    tags_filtered=tags_filtered,
                    success=False,
                    error="file_modified_externally",
                )
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=tags_filtered,
                success=False,
                error=f"Safe write failed: {result.error}",
            )

        # Sync mtime in DB so scanner skips this file on next scan
        if result.new_mtime_ms is not None:
            update_song_modified_time(db, file_id, result.new_mtime_ms)

        # Update file projection state in database
        set_file_written(db, file_key, worker_id)

        logger.debug(
            f"[write_file_tags] Wrote {len(tags_to_write) if tags_to_write is not None else 0} tags to {library_path.relative} "
            f"(mode={target_mode}, filtered={tags_filtered})",
        )

        return WriteResult(
            file_key=file_key,
            tags_written=len(tags_to_write) if tags_to_write is not None else 0,
            tags_filtered=tags_filtered,
            success=True,
        )

    except Exception as e:
        logger.exception(f"[write_file_tags] Failed to write tags for {file_key}")
        _release_failed_write(db, file_key, worker_id)
        return WriteResult(
            file_key=file_key,
            tags_written=0,
            tags_filtered=0,
            success=False,
            error=str(e),
        )
