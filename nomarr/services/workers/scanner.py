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

from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
from nomarr.services.queue_svc import ScanQueue
from nomarr.services.workers.base import BaseWorker
from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryScanWorker(BaseWorker):
    """
    Background worker for library scanning operations.

    Polls library_queue for pending scan jobs and executes them
    via scan_single_file_workflow. Each job processes ONE file.

    Inherits queue polling, state management, and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db: Database,
        event_broker: Any,
        namespace: str,
        interval: int = 5,
        worker_id: int = 0,
        auto_tag: bool = False,
        ignore_patterns: str = "",
    ):
        """
        Initialize LibraryScanWorker.

        Args:
            db: Database instance
            event_broker: Event broker for SSE state updates (required)
            namespace: Tag namespace for tag extraction
            interval: Polling interval in seconds (default: 5)
            worker_id: Unique worker ID (for multi-worker setups)
            auto_tag: Auto-enqueue untagged files for ML tagging (default: False)
            ignore_patterns: Comma-separated patterns to skip auto-tagging (default: "")
        """
        # Create scan queue wrapper
        scan_queue = ScanQueue(db)

        # Initialize parent BaseWorker
        super().__init__(
            name="LibraryScanWorker",
            queue=scan_queue,
            process_fn=self._process,
            db=db,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
        self.db = db
        self.namespace = namespace
        self.auto_tag = auto_tag
        self.ignore_patterns = ignore_patterns

    def _process(self, path: str, force: bool) -> dict[str, Any]:
        """
        Process a single file scan job.

        Args:
            path: File path to scan
            force: Whether to force rescan even if file hasn't changed

        Returns:
            Dict with scan results from workflow
        """
        params = ScanSingleFileWorkflowParams(
            file_path=path,
            namespace=self.namespace,
            force=force,
            auto_tag=self.auto_tag,
            ignore_patterns=self.ignore_patterns,
            library_id=None,  # Auto-determined from file path
        )
        return scan_single_file_workflow(db=self.db, params=params)
