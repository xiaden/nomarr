"""
Queue enqueue workflow - discover and enqueue audio files.

This workflow handles file discovery and batch enqueueing for audio processing.

ARCHITECTURE:
- Pure workflow that orchestrates: filesystem discovery + queue component calls
- Does NOT import services, interfaces, or app
- Callers provide db + queue_type + paths
- Uses queue components for enqueue operations

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance
- `queue_type: QueueType` - Which queue to use ("tag", "library", "calibration")
- `paths: str | list[str]` - File or directory paths to process
- `force: bool` - Whether to reprocess already-processed files
- `recursive: bool` - Whether to scan directories recursively

USAGE:
    from nomarr.workflows.queue.enqueue_files_wf import enqueue_files_workflow

    result = enqueue_files_workflow(
        db=database,
        queue_type="tag",
        paths=["/music/album1", "/music/single.mp3"],
        force=False,
        recursive=True
    )
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from nomarr.components.queue import check_file_needs_processing, enqueue_file, get_queue_depth
from nomarr.helpers.dto import ValidatedPath
from nomarr.helpers.dto.queue_dto import EnqueueFilesResult
from nomarr.helpers.files_helper import collect_audio_files

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def enqueue_files_workflow(
    db: Database,
    queue_type: QueueType,
    paths: str | list[str],
    force: bool = False,
    recursive: bool = True,
) -> EnqueueFilesResult:
    """
    Discover audio files from paths and enqueue them into specified queue.

    This workflow:
    1. Uses collect_audio_files() to safely discover audio files
    2. Checks each file if needs processing (unless force=True)
    3. Enqueues files via queue components
    4. Returns summary statistics

    Args:
        db: Database instance
        queue_type: Which queue to use ("tag", "library", "calibration")
        paths: Single path or list of paths (files or directories)
        force: If True, reprocess files even if already processed
        recursive: If True, recursively scan directories for audio files

    Returns:
        EnqueueFilesResult with:
            - job_ids: List of created job IDs
            - files_queued: Number of files added
            - queue_depth: Total pending jobs after adding
            - paths: Input paths (normalized to list)

    Raises:
        FileNotFoundError: If any path doesn't exist
        ValueError: If no audio files found at given paths
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
    logger.debug(f"[enqueue_files_wf] Discovering audio files from {len(paths)} path(s)")
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

    # Enqueue files using queue components
    job_ids = []
    skipped = 0
    for file_path in audio_files:
        # Check if file needs processing
        if check_file_needs_processing(db, file_path, force, queue_type):
            # Wrap in ValidatedPath - file is already validated by collect_audio_files()
            validated_path = ValidatedPath(path=file_path)
            job_id = enqueue_file(db, validated_path, force, queue_type)
            job_ids.append(job_id)
            logger.debug(f"[enqueue_files_wf] Queued job {job_id} for {file_path}")
        else:
            skipped += 1
            logger.debug(f"[enqueue_files_wf] Skipped unchanged file: {file_path}")

    # Get final queue depth
    queue_depth = get_queue_depth(db, queue_type)

    logger.info(
        f"[enqueue_files_wf] Queued {len(job_ids)} files from {len(paths)} path(s) "
        f"(skipped {skipped}, queue depth={queue_depth})"
    )

    return EnqueueFilesResult(
        job_ids=job_ids,
        files_queued=len(job_ids),
        queue_depth=queue_depth,
        paths=paths,
    )
