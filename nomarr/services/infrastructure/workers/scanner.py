#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Library Scanner Worker
"""
scanner.py
──────────
LibraryScanWorker class for queue-based library scanning.

Extends BaseWorker to provide per-file library scanning using the
library_queue table. Files are enqueued by start_library_scan_workflow
and processed one at a time by this worker.

Each job processes ONE file:
- Extracts metadata and tags
- Updates library_files table
- Optionally enqueues for ML tagging
"""
# ======================================================================

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nomarr.services.infrastructure.workers.base import BaseWorker

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def create_scanner_backend(
    namespace: str,
) -> Callable[[Database, str, bool], dict[str, Any]]:
    """
    Create a scanner backend function with captured config.

    This factory function creates a closure that captures application config
    and calls the scan_single_file_workflow with appropriate settings.

    The backend receives the worker's Database connection as its first parameter,
    ensuring connection reuse across jobs instead of creating a new connection per job.

    Args:
        namespace: Tag namespace for scanned files

    Returns:
        Callable backend function for LibraryScanWorker that accepts (db, path, force)
    """

    def scanner_backend(db: Database, path: str, force: bool):
        """Backend for LibraryScanWorker - scans library for new/changed files."""
        from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
        from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow

        params = ScanSingleFileWorkflowParams(
            file_path=path,
            namespace=namespace,
            force=force,
            auto_tag=True,  # Auto-enqueue discovered files for tagging
            ignore_patterns="",
            library_id=None,
        )
        return scan_single_file_workflow(db=db, params=params)

    return scanner_backend


class LibraryScanWorker(BaseWorker):
    """
    Background worker for library scanning operations.

    Polls library_queue table for pending scan jobs and executes them
    via a provided processing backend. Each job processes ONE file.

    Inherits queue polling, state management, and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db_path: str,
        processing_backend: Callable[[Database, str, bool], dict[str, Any]],
        event_broker: Any,
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize LibraryScanWorker.

        Args:
            db_path: Path to database file (worker creates its own connection)
            processing_backend: Backend function for processing files
            event_broker: Event broker for SSE state updates (required)
            interval: Polling interval in seconds (default: 5)
            worker_id: Unique worker ID (for multi-worker setups)
        """
        # Initialize parent BaseWorker with library queue type
        super().__init__(
            name="LibraryScanWorker",
            queue_type="library",
            process_fn=processing_backend,
            db_path=db_path,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
