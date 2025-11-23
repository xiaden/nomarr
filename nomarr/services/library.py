"""
Library service.
Shared business logic for library scanning across all interfaces.
"""

from __future__ import annotations

import logging
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
        paths: list[str] | None = None,
        recursive: bool = True,
        force: bool = False,
        clean_missing: bool = True,
    ) -> dict[str, Any]:
        """
        Start a library scan by discovering files and enqueueing them.

        This uses the new per-file scanning approach:
        1. Discovers audio files in specified paths
        2. Enqueues each file to library_queue
        3. LibraryScanWorker processes files in background

        Args:
            paths: List of paths to scan (defaults to configured library_path)
            recursive: Whether to scan subdirectories recursively
            force: Whether to force rescan even if files haven't changed
            clean_missing: Whether to remove deleted files from database

        Returns:
            Dict with scan statistics from start_library_scan_workflow

        Raises:
            ValueError: If library not configured
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured (no library_path)")

        # Default to configured library_path if no paths provided
        if paths is None:
            paths = [self.cfg.library_path]

        from nomarr.workflows.library.start_library_scan import start_library_scan_workflow

        logging.info(f"[LibraryService] Starting library scan for {len(paths)} path(s)")
        stats = start_library_scan_workflow(
            db=self.db,
            root_paths=paths,
            recursive=recursive,
            force=force,
            auto_tag=False,  # Auto-tagging is handled by LibraryScanWorker per file
            ignore_patterns="",
            clean_missing=clean_missing,
        )

        logging.info(
            f"[LibraryService] Scan planned: "
            f"discovered={stats['files_discovered']}, queued={stats['files_queued']}, "
            f"skipped={stats['files_skipped']}, removed={stats['files_removed']}"
        )
        # TypedDict is compatible with dict[str, Any] at runtime
        return dict(stats)  # type: ignore[return-value]

    def cancel_scan(self) -> bool:
        """
        Cancel the currently running scan.

        Note: With per-file scanning, this clears the pending queue.
        Files currently being processed will complete.

        Returns:
            Number of pending jobs cancelled

        Raises:
            ValueError: If library not configured
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        # Clear pending scan jobs from queue
        cleared = self.db.library_queue.clear_scan_queue()
        logging.info(f"[LibraryService] Cleared {cleared} pending scan jobs")
        return cleared > 0

    def get_status(self) -> dict[str, Any]:
        """
        Get current library scan status.

        Returns:
            Dict with:
                - configured: bool
                - library_path: str | None
                - enabled: bool (worker running)
                - pending_jobs: int (files waiting to be scanned)
                - running_jobs: int (files currently being scanned)
        """
        if not self.cfg.library_path:
            return {
                "configured": False,
                "library_path": None,
                "enabled": False,
                "pending_jobs": 0,
                "running_jobs": 0,
            }

        # Check if worker is available
        enabled = self.worker is not None

        # Count jobs by status
        pending_jobs = self.db.library_queue.count_pending_scans()
        jobs = self.db.library_queue.list_scan_jobs(limit=1000)
        running_jobs = sum(1 for job in jobs if job["status"] == "running")

        return {
            "configured": True,
            "library_path": self.cfg.library_path,
            "enabled": enabled,
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
        }

    def get_scan_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get recent library scan jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts with id, path, status, started_at, completed_at, etc.
        """
        return self.db.library_queue.list_scan_jobs(limit=limit)

    def get_library_stats(self) -> dict[str, Any]:
        """
        Get library statistics (total files, total duration, etc.).

        Returns:
            Dictionary with library statistics
        """
        return self.db.library_files.get_library_stats()

    def get_all_library_paths(self) -> list[str]:
        """
        Get all file paths in the library.

        Returns:
            List of absolute file paths
        """
        return self.db.library_files.get_all_library_paths()

    def _is_scan_running(self) -> bool:
        """
        Check if any scan jobs are currently being processed.

        Returns:
            True if any jobs are in 'running' status
        """
        # Query for any running scan jobs
        jobs = self.db.library_queue.list_scan_jobs(limit=1000)
        return any(job["status"] == "running" for job in jobs)

    def pause(self) -> bool:
        """
        Pause the library scanner worker.

        Returns:
            True if paused successfully

        Raises:
            ValueError: If library not configured
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        # Set worker_enabled=false in database meta
        self.db.meta.set("worker_enabled", "false")
        logging.info("[LibraryService] Library scanner paused via worker_enabled flag")
        return True

    def resume(self) -> bool:
        """
        Resume the library scanner worker.

        Returns:
            True if resumed successfully

        Raises:
            ValueError: If library not configured
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        # Set worker_enabled=true in database meta
        self.db.meta.set("worker_enabled", "true")
        logging.info("[LibraryService] Library scanner resumed via worker_enabled flag")
        return True

    def clear_library_data(self) -> None:
        """
        Clear all library data (files, tags, scan queue).

        This forces a fresh rescan by removing all existing library state.
        Does not affect the ML tagging queue or system metadata.

        Raises:
            ValueError: If library not configured
            RuntimeError: If scan jobs are currently running
        """
        if not self.cfg.library_path:
            raise ValueError("Library scanning not configured")

        # Check if any jobs are running
        if self._is_scan_running():
            raise RuntimeError("Cannot clear library while scan jobs are running. Cancel scans first.")

        self.db.library_files.clear_library_data()
        logging.info("[LibraryService] Library data cleared")
