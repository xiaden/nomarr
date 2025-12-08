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
from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams, UpdateLibraryFileFromTagsParams

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def scan_single_file_workflow(
    db: Database,
    params: ScanSingleFileWorkflowParams,
) -> dict[str, Any]:
    """
    Scan a single audio file and update library database.

    This workflow:
    1. Extracts metadata from the file
    2. Updates library_files table with current metadata
    3. Optionally enqueues file for ML tagging if untagged

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
    file_path = params.file_path
    namespace = params.namespace
    force = params.force
    auto_tag = params.auto_tag
    ignore_patterns = params.ignore_patterns
    library_id = params.library_id
    logging.debug(f"[scan_single_file] Scanning {file_path}")

    result: dict[str, Any] = {
        "success": False,
        "file_path": file_path,
        "action": "skipped",
        "error": None,
        "auto_tagged": False,
    }

    try:
        # Import workflow function for updating library file from tags
        import os

        from nomarr.workflows.library.scan_library_wf import update_library_file_from_tags

        # Determine library_id if not provided
        if library_id is None:
            library = db.libraries.find_library_containing_path(file_path)
            if not library:
                result["action"] = "error"
                result["error"] = "File path not in any configured library"
                logging.error(f"[scan_single_file] Path not in any library: {file_path}")
                return result
            library_id = library["id"]
            logging.debug(f"[scan_single_file] Auto-detected library_id={library_id} for {file_path}")

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
        if auto_tag:
            # Check if file needs tagging (new file or not yet tagged)
            needs_tagging = is_new or (
                existing_file is not None and not existing_file.get("tagged") and not existing_file.get("skip_auto_tag")
            )

            # Apply ignore patterns
            if needs_tagging and ignore_patterns:
                from nomarr.workflows.library.start_library_scan_wf import _matches_ignore_pattern

                if _matches_ignore_pattern(file_path, ignore_patterns):
                    needs_tagging = False

        if needs_tagging:
            # File needs tagging - skip metadata extraction, just enqueue for tagging
            # The tagger will extract metadata and write tags in one pass
            logging.debug(f"[scan_single_file] File needs tagging, skipping metadata extraction: {file_path}")
            enqueue_file(db, file_path, force=False, queue_type="tag")
            result["action"] = "queued_for_tagging"
            result["success"] = True
            result["auto_tagged"] = True
        else:
            # File doesn't need tagging - extract and update metadata now
            params_update = UpdateLibraryFileFromTagsParams(
                file_path=file_path,
                namespace=namespace,
                tagged_version=None,
                calibration=None,
                library_id=library_id,
            )
            update_library_file_from_tags(db, params_update)
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
