"""
Library service.
Shared business logic for library scanning across all interfaces.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.workers.scanner import LibraryScanWorker


class LibraryService:
    """
    Library scanning operations - shared by all interfaces.

    This service encapsulates library scanning logic, ensuring CLI and API
    coordinate properly when accessing the library_queue table.
    """

    def __init__(
        self,
        db: Database,
        namespace: str,
        library_path: str | None = None,
        worker: LibraryScanWorker | None = None,
    ):
        """
        Initialize library service.

        Args:
            db: Database instance
            namespace: Tag namespace for library operations (e.g., "nom")
            library_path: Path to music library directory
            worker: LibraryScanWorker instance (for background scans in API)
        """
        self.db = db
        self.namespace = namespace
        self.library_path = library_path
        self.worker = worker

    def is_configured(self) -> bool:
        """
        Check if library scanning is configured.

        Returns:
            True if library_path is set
        """
        return self.library_path is not None

    def start_scan(
        self,
        namespace: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        background: bool = False,
    ) -> int:
        """
        Start a library scan.

        Args:
            namespace: Optional tag namespace to filter by
            progress_callback: Optional callback for progress updates (file_num, total)
            background: If True, queue scan in worker (API). If False, run synchronously (CLI)

        Returns:
            Scan ID

        Raises:
            ValueError: If library not configured
            RuntimeError: If scan already running
        """
        if not self.library_path:
            raise ValueError("Library scanning not configured (no library_path)")

        # Check if scan already running (across CLI + API)
        if self._is_scan_running():
            raise RuntimeError("A library scan is already running")

        if background and self.worker:
            # API mode: queue scan in background worker
            # Note: LibraryScanWorker uses its own configured namespace
            scan_id = self.worker.request_scan()
            logging.info(f"[LibraryService] Queued background scan {scan_id}")
            return scan_id
        else:
            # CLI mode: run scan synchronously
            from nomarr.workflows.scan_library import scan_library_workflow

            logging.info("[LibraryService] Starting synchronous library scan")
            stats = scan_library_workflow(
                db=self.db,
                library_path=self.library_path,
                namespace=namespace if namespace is not None else self.namespace,
                progress_callback=progress_callback,
            )

            # Get the scan_id from the most recent scan
            scan_id = self.db.library.get_latest_scan_id() or 0

            logging.info(
                f"[LibraryService] Scan {scan_id} complete: "
                f"{stats['files_processed']} files, {stats['files_updated']} updated"
            )
            return scan_id

    def cancel_scan(self) -> bool:
        """
        Cancel the currently running scan.

        Returns:
            True if cancellation requested, False if no scan running

        Raises:
            ValueError: If library not configured
        """
        if not self.library_path:
            raise ValueError("Library scanning not configured")

        if self.worker:
            # API mode: cancel via worker
            self.worker.cancel_scan()
            logging.info("[LibraryService] Cancellation requested via worker")
            return True
        else:
            # CLI mode: cancellation handled by scan_library() checking a flag
            # (would need to implement cancellation mechanism in core/library_scanner.py)
            logging.warning("[LibraryService] CLI scan cancellation not yet implemented")
            return False

    def get_status(self) -> dict[str, Any]:
        """
        Get current library scan status.

        Returns:
            Dict with:
                - configured: bool
                - library_path: str | None
                - enabled: bool (worker running)
                - running: bool (scan in progress)
                - current_scan_id: int | None
                - current_progress: dict | None
        """
        if not self.library_path:
            return {
                "configured": False,
                "library_path": None,
                "enabled": False,
                "running": False,
                "current_scan_id": None,
                "current_progress": None,
            }

        # Check if worker is available
        enabled = self.worker is not None

        # Check database for running scans
        running = self._is_scan_running()
        current_scan_id = None
        current_progress = None

        if running:
            scan = self.db.library.get_running_scan()
            if scan:
                current_scan_id = scan["id"]
                current_progress = {
                    "files_processed": scan.get("files_processed") or 0,
                    "total_files": scan.get("total_files") or 0,
                    "current_file": scan.get("current_file"),
                }

        return {
            "configured": True,
            "library_path": self.library_path,
            "enabled": enabled,
            "running": running,
            "current_scan_id": current_scan_id,
            "current_progress": current_progress,
        }

    def get_scan_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent library scan history.

        Args:
            limit: Maximum number of scans to return

        Returns:
            List of scan dicts with id, status, started_at, finished_at, files_scanned, etc.
        """
        return self.db.library.list_scans(limit=limit)

    def _is_scan_running(self) -> bool:
        """
        Check if any scan is currently running (from CLI or API).

        Returns:
            True if a scan is in 'running' status
        """
        count = self.db.library.count_running_scans()
        return count > 0
