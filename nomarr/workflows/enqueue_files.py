"""
Queue operations workflow.

This workflow handles file discovery and batch enqueueing for audio processing.

ARCHITECTURE:
- Pure workflow that orchestrates: filesystem discovery + DB operations
- Does NOT import services, interfaces, or app
- Callers provide explicit dependencies

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance (workflow accesses db.queue directly)
- `paths: str | list[str]` - File or directory paths to process
- `force: bool` - Whether to reprocess already-tagged files
- `recursive: bool` - Whether to scan directories recursively

USAGE:
    from nomarr.workflows.enqueue_files import enqueue_files_workflow

    result = enqueue_files_workflow(
        db=database_instance,
        paths=["/music/album1", "/music/single.mp3"],
        force=False,
        recursive=True
    )
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from nomarr.helpers.files import collect_audio_files

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def enqueue_files_workflow(
    db: Database,
    paths: str | list[str],
    force: bool = False,
    recursive: bool = True,
) -> dict[str, Any]:
    """
    Discover audio files from paths and enqueue them for processing.

    This workflow:
    1. Validates that all paths exist
    2. Discovers audio files (recursively if enabled)
    3. Enqueues each file in the processing queue
    4. Returns summary statistics

    Args:
        db: Database instance for queue operations
        paths: Single path or list of paths (files or directories)
        force: If True, reprocess files even if already tagged
        recursive: If True, recursively scan directories for audio files

    Returns:
        Dict with:
            - job_ids: List of created job IDs
            - files_queued: Number of files added
            - queue_depth: Total pending jobs after adding
            - paths: Input paths (normalized to list)

    Raises:
        FileNotFoundError: If any path doesn't exist
        ValueError: If no audio files found at given paths

    Example:
        >>> result = enqueue_files_workflow(queue=my_queue, paths="/music/library", force=False, recursive=True)
        >>> print(f"Queued {result['files_queued']} files")
    """
    # Normalize paths to list
    if isinstance(paths, str):
        paths = [paths]

    # Validate paths exist
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Path not found: {path}")

    # Discover audio files from all paths
    logger.debug(f"[queue_workflow] Discovering audio files from {len(paths)} path(s)")
    audio_files = collect_audio_files(paths, recursive=recursive)

    if not audio_files:
        # Determine error message based on input type
        if len(paths) == 1 and os.path.isdir(paths[0]):
            raise ValueError(f"No audio files found in directory: {paths[0]}")
        elif len(paths) == 1:
            raise ValueError(f"Not an audio file: {paths[0]}")
        else:
            raise ValueError(f"No audio files found in provided paths: {paths}")

    # Enqueue all discovered files
    job_ids = []
    for file_path in audio_files:
        job_id = db.queue.enqueue(file_path, force)
        job_ids.append(job_id)
        logger.debug(f"[queue_workflow] Queued job {job_id} for {file_path}")

    # Get final queue depth
    queue_depth = db.queue.queue_depth()

    logger.info(f"[queue_workflow] Queued {len(job_ids)} files from {len(paths)} path(s) (queue depth={queue_depth})")

    return {
        "job_ids": job_ids,
        "files_queued": len(job_ids),
        "queue_depth": queue_depth,
        "paths": paths,
    }
