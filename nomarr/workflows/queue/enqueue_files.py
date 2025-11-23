"""
Queue operations workflow.

This workflow handles file discovery and batch enqueueing for audio processing.

ARCHITECTURE:
- Pure infrastructure workflow that orchestrates: filesystem discovery + queue operations
- Does NOT import services, interfaces, or app
- Callers provide explicit dependencies
- Queue-agnostic: works with any queue that has an enqueue(path, force) method

PATH VALIDATION:
- This workflow uses helpers.files.collect_audio_files() which safely handles:
  - Existence checking
  - Audio file filtering
  - Directory traversal
- For user-controlled paths, callers should validate through helpers.files first
- This workflow will skip non-existent paths gracefully via collect_audio_files()

EXPECTED DEPENDENCIES:
- `queue: QueueProtocol` - Any queue object with enqueue(path, force) -> int method
  Examples: ProcessingQueue, ScanQueue, RecalibrationQueue from services.queue
  Or raw DB facades: db.tag_queue, db.library_queue, db.calibration_queue (if wrapped)
- `paths: str | list[str]` - File or directory paths to process
- `force: bool` - Whether to reprocess already-processed files
- `recursive: bool` - Whether to scan directories recursively

USAGE:
    from nomarr.workflows.queue.enqueue_files import enqueue_files_workflow
    from nomarr.services.queue_service import ProcessingQueue

    queue = ProcessingQueue(db)
    result = enqueue_files_workflow(
        queue=queue,
        paths=["/music/album1", "/music/single.mp3"],
        force=False,
        recursive=True
    )
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from nomarr.helpers.files import collect_audio_files

if TYPE_CHECKING:
    pass


class QueueProtocol(Protocol):
    """
    Protocol for queue objects that can enqueue file paths.

    Any object with an enqueue method matching this signature can be used
    with enqueue_files_workflow.
    """

    def enqueue(self, path: str, force: bool = False) -> int:
        """Enqueue a file path and return job ID."""
        ...

    def depth(self) -> int:
        """Return number of pending jobs."""
        ...


logger = logging.getLogger(__name__)


def enqueue_files_workflow(
    queue: QueueProtocol,
    paths: str | list[str],
    force: bool = False,
    recursive: bool = True,
) -> dict[str, Any]:
    """
    Discover audio files from paths and enqueue them into the given queue.

    This is a generalized infrastructure workflow that:
    1. Uses collect_audio_files() to safely discover audio files
    2. Enqueues each discovered file into the provided queue
    3. Returns summary statistics

    Args:
        queue: Queue object with enqueue(path, force) method
               (e.g., ProcessingQueue, ScanQueue, RecalibrationQueue)
        paths: Single path or list of paths (files or directories)
        force: If True, reprocess files even if already processed
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
        >>> from nomarr.services.queue_service import ProcessingQueue
        >>> queue = ProcessingQueue(db)
        >>> result = enqueue_files_workflow(queue=queue, paths="/music/library", force=False, recursive=True)
        >>> print(f"Queued {result['files_queued']} files")
    """
    # Normalize paths to list
    if isinstance(paths, str):
        paths = [paths]

    # Validate paths exist using Path objects (library-safe check)
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

    # Discover audio files from all paths
    # collect_audio_files() handles: existence checks, audio filtering, directory traversal
    logger.debug(f"[queue_workflow] Discovering audio files from {len(paths)} path(s)")
    audio_files = collect_audio_files(paths, recursive=recursive)

    if not audio_files:
        # Determine error message based on input type
        if len(paths) == 1:
            path = Path(paths[0])
            if path.is_dir():
                raise ValueError(f"No audio files found in directory: {path}")
            else:
                raise ValueError(f"Not an audio file: {path}")
        else:
            raise ValueError(f"No audio files found in provided paths: {paths}")

    # Enqueue all discovered files into the provided queue
    job_ids = []
    for file_path in audio_files:
        job_id = queue.enqueue(file_path, force)
        job_ids.append(job_id)
        logger.debug(f"[queue_workflow] Queued job {job_id} for {file_path}")

    # Get final queue depth
    queue_depth = queue.depth()

    logger.info(f"[queue_workflow] Queued {len(job_ids)} files from {len(paths)} path(s) (queue depth={queue_depth})")

    return {
        "job_ids": job_ids,
        "files_queued": len(job_ids),
        "queue_depth": queue_depth,
        "paths": paths,
    }
