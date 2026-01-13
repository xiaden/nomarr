"""Queue enqueue operations - add files to processing queues."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def check_file_needs_processing(db: Database, path: LibraryPath, force: bool, queue_type: QueueType) -> bool:
    """
    Check if a file needs to be added to the queue for processing.

    For tag queue: checks if file has been modified since last tagging
    For library queue: checks if file has been modified since last scan
    For calibration queue: always returns True (calibration always reprocesses)

    Args:
        db: Database instance
        path: LibraryPath with validated file path
        force: If True, always return True (force reprocessing)
        queue_type: Which queue to check against

    Returns:
        True if file should be enqueued, False if can be skipped
    """
    if force:
        return True

    if queue_type == "calibration":
        # Calibration always reprocesses existing tags
        return True

    # Check file modification time
    path_str = str(path.absolute)
    if not os.path.exists(path_str):
        logger.warning(f"File does not exist: {path_str}")
        return False

    try:
        file_stat = os.stat(path_str)
        modified_time = int(file_stat.st_mtime * 1000)
    except OSError as e:
        logger.warning(f"Cannot stat file {path_str}: {e}")
        return False

    # Check against database records
    if queue_type == "tag":
        # Check if file has been tagged and modification time matches
        existing = db.library_files.get_library_file(path_str)
        if existing and existing.get("modified_time") == modified_time:  # noqa: SIM103
            # File unchanged since last tag
            return False
        return True

    elif queue_type == "library":
        # Check if file has been scanned and modification time matches
        existing = db.library_files.get_library_file(path_str)
        if existing and existing.get("modified_time") == modified_time:  # noqa: SIM103
            # File unchanged since last scan
            return False
        return True

    return True


def enqueue_file(db: Database, path: LibraryPath, force: bool, queue_type: QueueType) -> int:
    """
    Enqueue a single file for processing.

    Routes to appropriate queue based on queue_type.

    Args:
        db: Database instance
        path: LibraryPath with validated file path
        force: Whether to force reprocessing (passed to tag/library queues)
        queue_type: Which queue to add to ("tag", "library", "calibration")

    Returns:
        Job ID of enqueued job

    Raises:
        ValueError: If queue_type is invalid or path status is not valid
        RuntimeError: If database operation fails
    """
    # Enforce that path must be valid before enqueueing
    if not path.is_valid():
        raise ValueError(f"Cannot enqueue invalid path ({path.status}): {path.reason}")

    logger.debug(f"Enqueueing file to {queue_type} queue: {path.absolute}")

    if queue_type == "tag":
        return db.tag_queue.enqueue(path, force)
    elif queue_type == "calibration":
        return db.calibration_queue.enqueue_calibration(path)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def enqueue_file_checked(db: Database, path: LibraryPath, force: bool, queue_type: QueueType) -> int | None:
    """
    Check if file needs processing, then enqueue if needed.

    Combines check_file_needs_processing() and enqueue_file() for convenience.

    Args:
        db: Database instance
        path: LibraryPath with validated file path
        force: Whether to force reprocessing
        queue_type: Which queue to add to

    Returns:
        Job ID if file was enqueued, None if skipped

    Raises:
        ValueError: If queue_type is invalid or path status is not valid
        RuntimeError: If database operation fails
    """
    if not check_file_needs_processing(db, path, force, queue_type):
        logger.debug(f"Skipping unchanged file: {path.absolute}")
        return None

    return enqueue_file(db, path, force, queue_type)
