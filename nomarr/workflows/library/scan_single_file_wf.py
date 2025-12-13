"""
Workflow for scanning a single file and updating library database.

This workflow handles the EXECUTION phase of library scanning:
- Extracts metadata from a single audio file
- Updates library_files table
- Optionally enqueues file for ML tagging if needed

This is called by LibraryScanWorker for each file in the queue.

ARCHITECTURE:
- This is a PURE WORKFLOW that takes all dependencies as parameters
- Does NOT import or use services, DI container, or application object
- Callers (typically workers) must provide Database instance and config values

EXPECTED DATABASE INTERFACE:
The `db` parameter must provide:
- db.library_files.upsert_library_file(path, **metadata) -> int
- db.library_files.get_library_file(path) -> dict | None
- db.library_tags.upsert_file_tags(file_id, tags) -> None

EXPECTED COMPONENTS:
- enqueue_file() from nomarr.components.queue (for auto-tagging untagged files)

USAGE:
    from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow

    result = scan_single_file_workflow(
        db=database_instance,
        file_path="/path/to/file.flac",
        namespace="nom",
        force=False,
        auto_tag=True,
        ignore_patterns="*/Audiobooks/*"
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.queue import enqueue_file
from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
from nomarr.helpers.dto.path_dto import build_library_path_from_db

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def scan_single_file_workflow(
    db: Database,
    params: ScanSingleFileWorkflowParams,
) -> dict[str, Any]:
    """
    Scan a single audio file and update library database.

    This workflow:
    1. Validates the file path (converts string to LibraryPath)
    2. Checks path status against current configuration
    3. Extracts metadata from the file
    4. Updates library_files table with current metadata
    5. Optionally enqueues file for ML tagging if untagged

    Args:
        db: Database instance (must provide library, tags, and queue accessors)
        params: ScanSingleFileWorkflowParams with file_path, namespace, force, auto_tag, ignore_patterns, library_id

    Returns:
        Dict with scan results:
        - success: bool
        - file_path: str
        - action: str ("added", "updated", "skipped", "error")
        - error: str | None (error message if action="error")
        - auto_tagged: bool (whether file was enqueued for tagging)

    Raises:
        Exception: On scan failure (caller should handle and mark job as error)
    """
    # Extract parameters
    file_path_str = params.file_path
    namespace = params.namespace
    force = params.force
    auto_tag = params.auto_tag
    ignore_patterns = params.ignore_patterns
    library_id = params.library_id
    version_tag_key = params.version_tag_key
    tagger_version = params.tagger_version
    logging.debug(f"[scan_single_file] Scanning {file_path_str}")

    result: dict[str, Any] = {
        "success": False,
        "file_path": file_path_str,
        "action": "skipped",
        "error": None,
        "auto_tagged": False,
    }

    try:
        # Import components for metadata extraction and library update
        import os

        # Validate the path against current library configuration
        # This handles cases where library root has changed since path was queued
        library_path = build_library_path_from_db(
            stored_path=file_path_str,
            db=db,
            library_id=library_id,
            check_disk=True,
        )

        # Check if path is valid under current configuration
        if not library_path.is_valid():
            result["action"] = "error"
            result["error"] = f"Path validation failed: {library_path.status} - {library_path.reason}"
            logging.error(
                f"[scan_single_file] Path invalid ({library_path.status}): {file_path_str} - {library_path.reason}"
            )
            return result

        # Use validated path for remaining operations
        file_path = str(library_path.absolute)
        library_id = library_path.library_id

        logging.debug(f"[scan_single_file] Path validated for library_id={library_id}: {file_path}")

        # Check if file exists
        if not os.path.exists(file_path):
            result["action"] = "error"
            result["error"] = "File not found"
            return result

        # Get file modification time
        file_stat = os.stat(file_path)
        modified_time = int(file_stat.st_mtime * 1000)

        # Check if file needs scanning (unless force=True)
        if not force:
            existing_file = db.library_files.get_library_file(file_path)
            if existing_file and existing_file["modified_time"] == modified_time:
                # File hasn't changed, skip
                result["action"] = "skipped"
                result["success"] = True
                return result

        # Get existing file record to determine if this is add or update
        existing_file = db.library_files.get_library_file(file_path)
        is_new = existing_file is None

        # Optimization: If auto-tagging is enabled and file needs tagging,
        # skip metadata extraction here - the tagger will extract and write everything
        needs_tagging = False
        check_existing_version = False  # Track if we should check for existing version tag

        if auto_tag:
            # Check if file needs tagging (new file or not yet tagged)
            needs_tagging = is_new or (
                existing_file is not None and not existing_file.get("tagged") and not existing_file.get("skip_auto_tag")
            )

            # If file appears to need tagging and overwrite_tags=False, check if file already has our version tag
            # This handles the case where DB was wiped but files still have tags
            if needs_tagging and not force:
                check_existing_version = True

            # Apply ignore patterns
            if needs_tagging and ignore_patterns:
                from nomarr.workflows.library.start_library_scan_wf import _matches_ignore_pattern

                if _matches_ignore_pattern(file_path, ignore_patterns):
                    needs_tagging = False

        if needs_tagging and check_existing_version:
            # Extract metadata once to check version tag
            from nomarr.components.library.metadata_extraction_comp import extract_metadata

            file_metadata = extract_metadata(file_path, namespace=namespace)
            existing_version = file_metadata.get("nom_tags", {}).get(version_tag_key)

            if existing_version == tagger_version:
                # File already tagged with current version - import tags and mark as tagged
                logging.debug(
                    f"[scan_single_file] File already tagged with version {tagger_version}, importing tags: {file_path}"
                )
                from nomarr.components.library.library_update_comp import update_library_from_tags

                update_library_from_tags(
                    db=db,
                    file_path=file_path,
                    metadata=file_metadata,
                    namespace=namespace,
                    tagged_version=tagger_version,
                    calibration=None,
                    library_id=library_id,
                )
                logging.debug(f"[scan_single_file] Tags imported to DB for {file_path}")
                result["action"] = "added" if is_new else "updated"
                result["success"] = True
                needs_tagging = False
            elif existing_version:
                # File has old version - queue for retagging (don't import old tags)
                logging.debug(
                    f"[scan_single_file] File tagged with old version {existing_version} (current: {tagger_version}), queuing for retag: {file_path}"
                )

        if needs_tagging:
            # File needs tagging - skip metadata extraction, just enqueue for tagging
            # The tagger will extract metadata and write tags in one pass
            logging.debug(f"[scan_single_file] File needs tagging, skipping metadata extraction: {file_path}")
            enqueue_file(db, library_path, force=False, queue_type="tag")
            result["action"] = "queued_for_tagging"
            result["success"] = True
            result["auto_tagged"] = True
        elif not check_existing_version or (check_existing_version and result.get("success") is not True):
            # File doesn't need tagging - extract and update metadata now
            # Skip if we already handled it above (check_existing_version path)
            from nomarr.components.library.library_update_comp import update_library_from_tags
            from nomarr.components.library.metadata_extraction_comp import extract_metadata

            file_metadata = extract_metadata(file_path, namespace=namespace)
            update_library_from_tags(
                db=db,
                file_path=file_path,
                metadata=file_metadata,
                namespace=namespace,
                tagged_version=None,
                calibration=None,
                library_id=library_id,
            )
            result["action"] = "added" if is_new else "updated"
            result["success"] = True

        logging.debug(f"[scan_single_file] Completed {file_path}: {result['action']}")
        return result

    except Exception as e:
        logging.error(f"[scan_single_file] Failed to scan {file_path}: {e}")
        result["action"] = "error"
        result["error"] = str(e)
        result["success"] = False
        raise  # Re-raise so worker can mark job as error
