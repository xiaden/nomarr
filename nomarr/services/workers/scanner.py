#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Library Scanner Worker
"""
scanner.py
──────────
LibraryScanWorker class for queue-based library scanning.

Extends BaseWorker to provide systematic library scanning using the
library_queue table. Scans are requested via enqueue and processed
in order like other workers.

Note: Unlike file processing workers (TaggerWorker, RecalibrationWorker),
scanner processes scan_id integers (not file paths) since a scan covers
the entire library in one operation.
"""
# ======================================================================

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.services.queue import ScanQueue
from nomarr.services.workers.base import BaseWorker
from nomarr.workflows.scan_library import scan_library_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryScanWorker(BaseWorker):
    """
    Background worker for library scanning operations.

    Polls library_queue for pending scan requests and executes them
    via scan_library_workflow. Follows the same pattern as TaggerWorker
    and RecalibrationWorker.

    Inherits queue polling, state management, and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db: Database,
        event_broker: Any,
        library_path: str,
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
            library_path: Root path to scan
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
        self.library_path = library_path
        self.namespace = namespace
        self.auto_tag = auto_tag
        self.ignore_patterns = ignore_patterns

    def _process(self, path: str, force: bool) -> dict[str, Any]:
        """
        Process a library scan.

        Args:
            path: Unused (placeholder from BaseWorker interface)
            force: Unused (scans always process entire library)

        Returns:
            Dict with scan statistics

        Note: Accesses scan_id via self._current_job_id from BaseWorker
        """
        scan_id = self._current_job_id
        if scan_id is None:
            raise RuntimeError("No scan_id available - _process called outside job context")

        # Progress callback for workflow
        def progress_callback(current: int, total: int) -> None:
            """Update scan progress in database."""
            self.db.library.update_library_scan(
                scan_id,
                files_scanned=current,
            )

        # Run scan workflow
        stats = scan_library_workflow(
            self.db,
            self.library_path,
            self.namespace,
            progress_callback,
            scan_id=scan_id,
            auto_tag=self.auto_tag,
            ignore_patterns=self.ignore_patterns,
        )

        return stats
