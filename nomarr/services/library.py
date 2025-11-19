"""
Library service.
Shared business logic for library scanning across all interfaces.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.workers.scanner import LibraryScanWorker


@dataclass
class LibraryConfig:
    """Configuration for LibraryService."""

    namespace: str
    library_path: str | None


class LibraryService:
    """
    Library scanning operations - shared by all interfaces.

    This service encapsulates library scanning logic, ensuring CLI and API
    coordinate properly when accessing the library_queue table.
    """

    def __init__(
        self,
        db: Database,
        cfg: LibraryConfig,
        worker: LibraryScanWorker | None = None,
    ):
        """
        Initialize library service.

        Args:
            db: Database instance
            cfg: Library configuration
            worker: LibraryScanWorker instance (for background scans in API)
        """
        self.db = db
        self.cfg = cfg
        self.worker = worker

    def is_configured(self) -> bool:
        """
        Check if library scanning is configured.

        Returns:
            True if library_path is set
        """
        return self.cfg.library_path is not None

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
        if not self.cfg.library_path:
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
                library_path=self.cfg.library_path,
                namespace=namespace if namespace is not None else self.cfg.namespace,
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
        if not self.cfg.library_path:
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
        if not self.cfg.library_path:
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
            "library_path": self.cfg.library_path,
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

    def get_library_stats(self) -> dict[str, Any]:
        """
        Get library statistics (total files, total duration, etc.).

        Returns:
            Dictionary with library statistics
        """
        return self.db.library.get_library_stats()

    def get_all_library_paths(self) -> list[str]:
        """
        Get all file paths in the library.

        Returns:
            List of absolute file paths
        """
        return self.db.library.get_all_library_paths()

    def _is_scan_running(self) -> bool:
        """
        Check if any scan is currently running (from CLI or API).

        Returns:
            True if a scan is in 'running' status
        """
        count = self.db.library.count_running_scans()
        return count > 0

    def pause(self) -> bool:
        """
        Pause the library scanner worker.

        Returns:
            True if paused successfully

        Raises:
            ValueError: If library not configured or worker not available
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        if not self.worker:
            raise ValueError("Library scan worker not available")

        self.worker.pause()
        logging.info("[LibraryService] Library scanner paused")
        return True

    def resume(self) -> bool:
        """
        Resume the library scanner worker.

        Returns:
            True if resumed successfully

        Raises:
            ValueError: If library not configured or worker not available
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        if not self.worker:
            raise ValueError("Library scan worker not available")

        self.worker.resume()
        logging.info("[LibraryService] Library scanner resumed")
        return True

    def clear_library_data(self) -> None:
        """
        Clear all library data (files, tags, scans).

        This forces a fresh rescan by removing all existing library state.
        Does not affect the job queue or system metadata.

        Raises:
            ValueError: If library not configured
            RuntimeError: If a scan is currently running
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        # Check if scan is running
        if self._is_scan_running():
            raise RuntimeError("Cannot clear library while a scan is running. Cancel the scan first.")

        self.db.library.clear_library_data()
        logging.info("[LibraryService] Library data cleared")
