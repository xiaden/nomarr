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

from typing import TYPE_CHECKING, Any

from nomarr.services.infrastructure.workers.base import BaseWorker

if TYPE_CHECKING:
    from nomarr.services.processing_backends import ProcessingBackend


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
        processing_backend: ProcessingBackend,
        event_broker: Any,
        interval: int = 5,
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
