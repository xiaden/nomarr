"""
File tag writing workflow - writes DB tags to audio files.

This workflow writes tags from the database to audio files based on
the library's file_write_mode setting. It handles mode filtering,
calibration requirements, and atomic safe writes.

ARCHITECTURE:
- DB is the source of truth for all tags
- Files are projections controlled per-library
- Mood tags require calibration - filtered out when calibration is empty
- Uses existing TagWriter with atomic safe writes

MODES:
- "none": Remove all essentia:* tags (call TagWriter with tags={})
- "minimal": Only mood-tier tags (mood-strict, mood-regular, mood-loose)
- "full": All available tags from DB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.helpers.dto.tags_dto import Tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result from write_file_tags_workflow."""

    file_key: str  # Document _key of the file
    tags_written: int  # Number of tags written to file
    tags_filtered: int  # Number of tags filtered out by mode
    success: bool  # Whether write succeeded
    error: str | None = None  # Error message if failed


def _filter_tags_for_mode(
    db_tags: Tags,
    target_mode: str,
    has_calibration: bool,
) -> Tags:
    """
    Filter tags based on target mode and calibration state.

    Args:
        db_tags: All tags from database (Tags DTO)
        target_mode: "none", "minimal", or "full"
        has_calibration: Whether calibration exists

    Returns:
        Filtered Tags DTO for file writing
    """
    # Filter out mood tags if uncalibrated (applies to ALL modes)
    if not has_calibration:
        filtered_items = tuple(tag for tag in db_tags.items if not tag.key.startswith("mood-"))
    else:
        filtered_items = db_tags.items  # Already a tuple

    if target_mode == "none":
        return Tags(items=())  # Clears namespace

    if target_mode == "minimal":
        # Only mood-tier tags
        return Tags(items=tuple(tag for tag in filtered_items if tag.key.startswith("mood-")))

    # "full" mode - return all tags (already mood-filtered if uncalibrated)
    return Tags(items=filtered_items)


def _resolve_library_path(
    file_doc: dict[str, Any],
    db: Database,
) -> LibraryPath | None:
    """Resolve file_doc to a validated LibraryPath."""
    from nomarr.components.infrastructure.path_comp import build_library_path_from_db

    stored_path = file_doc.get("path", "")
    library_id = file_doc.get("library_id")

    library_path = build_library_path_from_db(
        stored_path=stored_path,
        db=db,
        library_id=library_id,
        check_disk=True,
    )

    return library_path if library_path.is_valid() else None


def write_file_tags_workflow(
    db: Database,
    file_key: str,
    target_mode: str,
    calibration_hash: str | None,
    has_calibration: bool,
    namespace: str = "nom",
) -> WriteResult:
    """
    Write tags from database to an audio file based on mode.

    This workflow reads tags from the database and writes them to the audio
    file using the appropriate mode filtering. It uses atomic safe writes
    via TagWriter to prevent file corruption.

    Args:
        db: Database instance
        file_key: Document _key of the file to write
        target_mode: Desired write mode ("none", "minimal", "full")
        calibration_hash: Current calibration hash
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
        # Normalize file_key
        if file_key.startswith("library_files/"):
            file_id = file_key
            file_key = file_key.split("/")[1]
        else:
            file_id = f"library_files/{file_key}"

        # Get file document
        file_doc = db.library_files.get_file_by_id(file_id)
        if not file_doc:
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"File not found: {file_id}",
            )

        # Resolve library path
        library_path = _resolve_library_path(file_doc, db)
        if not library_path:
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Invalid path: {file_doc.get('path')}",
            )

        # Get library root for safe write
        library_id = file_doc.get("library_id")
        if not library_id or not isinstance(library_id, str):
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Invalid library_id: {library_id}",
            )
        library_doc = db.libraries.get_library(library_id)
        if not library_doc:
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                error=f"Library not found: {library_id}",
            )
        library_root = Path(library_doc["root_path"])

        # Get chromaprint for verification
        chromaprint = file_doc.get("chromaprint")

        # Get tags from database (nomarr tags only) - returns Tags DTO
        db_tags = db.tags.get_song_tags(file_id, nomarr_only=True)

        # Filter tags for target mode
        tags_to_write = _filter_tags_for_mode(db_tags, target_mode, has_calibration)
        tags_filtered = len(db_tags) - len(tags_to_write)

        # Create tag writer with overwrite=True to clear namespace first
        tag_writer = TagWriter(overwrite=True, namespace=namespace)

        # Write tags using safe atomic write
        if chromaprint:
            result = tag_writer.write_safe(library_path, tags_to_write, library_root, chromaprint)
            if not result.success:
                # Release claim but don't update state
                db.library_files.release_claim(file_key)
                return WriteResult(
                    file_key=file_key,
                    tags_written=0,
                    tags_filtered=tags_filtered,
                    success=False,
                    error=f"Safe write failed: {result.error}",
                )
        else:
            # Fallback to direct write (no chromaprint available)
            logger.warning(f"[write_file_tags] No chromaprint for {file_key}, using direct write")
            tag_writer.write(library_path, tags_to_write)

        # Update file projection state in database
        db.library_files.set_file_written(file_key, mode=target_mode, calibration_hash=calibration_hash)

        logger.debug(
            f"[write_file_tags] Wrote {len(tags_to_write)} tags to {library_path.relative} "
            f"(mode={target_mode}, filtered={tags_filtered})"
        )

        return WriteResult(
            file_key=file_key,
            tags_written=len(tags_to_write),
            tags_filtered=tags_filtered,
            success=True,
        )

    except Exception as e:
        logger.exception(f"[write_file_tags] Failed to write tags for {file_key}")
        # Release claim on error
        try:
            db.library_files.release_claim(file_key)
        except Exception:
            pass
        return WriteResult(
            file_key=file_key,
            tags_written=0,
            tags_filtered=0,
            success=False,
            error=str(e),
        )
