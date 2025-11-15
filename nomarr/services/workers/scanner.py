"""
Background library scanner worker.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from nomarr.persistence.db import Database
from nomarr.workflows.library_scanner import scan_library

if TYPE_CHECKING:
    pass


class LibraryScanWorker:
    """Background worker that performs library scans asynchronously."""

    def __init__(
        self,
        db: Database,
        library_path: str,
        namespace: str = "essentia",
        poll_interval: int = 5,
        auto_tag: bool = False,
        ignore_patterns: str = "",
    ):
        """
        Initialize library scan worker.

        Args:
            db: Database instance
            library_path: Root path to scan
            namespace: Tag namespace for essentia tags
            poll_interval: Seconds between checking for new scan requests
            auto_tag: Auto-enqueue untagged files for ML tagging
            ignore_patterns: Comma-separated patterns to skip auto-tagging
        """
        self.db = db
        self.library_path = library_path
        self.namespace = namespace
        self.poll_interval = poll_interval
        self.auto_tag = auto_tag
        self.ignore_patterns = ignore_patterns
        self.running = False
        self.enabled = True
        self.thread: threading.Thread | None = None
        self.current_scan_id: int | None = None
        self.cancel_requested = False

    def start(self):
        """Start the worker thread."""
        if self.thread and self.thread.is_alive():
            logging.warning("[LibraryScanWorker] Already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="LibraryScanWorker")
        self.thread.start()
        logging.info("[LibraryScanWorker] Started")

    def stop(self):
        """Stop the worker thread."""
        logging.info("[LibraryScanWorker] Stopping...")
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logging.info("[LibraryScanWorker] Stopped")

    def pause(self):
        """Pause the worker (stop processing new scans)."""
        self.enabled = False
        logging.info("[LibraryScanWorker] Paused")

    def resume(self):
        """Resume the worker."""
        self.enabled = True
        logging.info("[LibraryScanWorker] Resumed")

    def request_scan(self) -> int:
        """
        Request a new library scan.

        Returns:
            scan_id: ID of the created scan record
        """
        scan_id = self.db.create_library_scan()
        logging.info(f"[LibraryScanWorker] Scan requested: {scan_id}")
        return scan_id

    def cancel_scan(self):
        """Cancel the currently running scan."""
        if self.current_scan_id:
            self.cancel_requested = True
            logging.info(f"[LibraryScanWorker] Cancel requested for scan {self.current_scan_id}")

    def get_status(self) -> dict:
        """
        Get current worker status.

        Returns:
            Dict with: enabled, running, current_scan_id, current_progress
        """
        progress = None
        if self.current_scan_id:
            scan_record = self.db.get_library_scan(self.current_scan_id)
            if scan_record:
                progress = {
                    "scan_id": self.current_scan_id,
                    "started_at": scan_record.get("started_at"),
                    "files_scanned": scan_record.get("files_scanned", 0),
                    "files_added": scan_record.get("files_added", 0),
                    "files_updated": scan_record.get("files_updated", 0),
                    "files_removed": scan_record.get("files_removed", 0),
                }

        return {
            "enabled": self.enabled,
            "running": self.running,
            "current_scan_id": self.current_scan_id,
            "current_progress": progress,
        }

    def _worker_loop(self):
        """Main worker loop - polls for pending scans and executes them."""
        logging.info("[LibraryScanWorker] Worker loop started")

        while self.running:
            try:
                if not self.enabled:
                    time.sleep(self.poll_interval)
                    continue

                # Check for pending scans
                pending = self._get_pending_scan()
                if not pending:
                    time.sleep(self.poll_interval)
                    continue

                # Execute the scan
                scan_id = pending["id"]
                self.current_scan_id = scan_id
                self.cancel_requested = False

                # Mark scan as 'running' now that we're actually processing it
                self.db.update_library_scan(scan_id, status="running")

                logging.info(f"[LibraryScanWorker] Starting scan {scan_id}")

                try:
                    # Progress tracking with proper closure binding
                    def make_progress_callback(scan_id: int):
                        def progress_callback(current: int, total: int):
                            # Update database periodically
                            self.db.update_library_scan(
                                scan_id,
                                files_scanned=current,
                            )
                            # Check for cancel request
                            if self.cancel_requested:
                                raise KeyboardInterrupt("Scan cancelled by user")

                        return progress_callback

                    # Run the scan
                    stats = scan_library(
                        self.db,
                        self.library_path,
                        self.namespace,
                        make_progress_callback(scan_id),
                        scan_id=scan_id,  # Pass scan_id so it updates the correct record
                        auto_tag=self.auto_tag,  # Pass auto-tag config
                        ignore_patterns=self.ignore_patterns,  # Pass ignore patterns
                    )

                    logging.info(
                        f"[LibraryScanWorker] Scan {scan_id} complete: "
                        f"scanned={stats['files_scanned']}, added={stats['files_added']}, "
                        f"updated={stats['files_updated']}, removed={stats['files_removed']}"
                    )

                except KeyboardInterrupt:
                    # Cancelled
                    logging.info(f"[LibraryScanWorker] Scan {scan_id} cancelled")
                    self.db.update_library_scan(
                        scan_id,
                        status="cancelled",
                        error_message="Cancelled by user",
                    )

                except Exception as e:
                    # Error
                    logging.error(f"[LibraryScanWorker] Scan {scan_id} failed: {e}")
                    self.db.update_library_scan(
                        scan_id,
                        status="error",
                        error_message=str(e),
                    )

                finally:
                    self.current_scan_id = None
                    self.cancel_requested = False

            except Exception as e:
                logging.error(f"[LibraryScanWorker] Worker loop error: {e}")
                time.sleep(self.poll_interval)

        logging.info("[LibraryScanWorker] Worker loop ended")

    def _get_pending_scan(self) -> dict | None:
        """Get the oldest pending scan request."""
        scans = self.db.list_library_scans(limit=100)
        for scan in scans:
            # Skip scan if already being processed
            if scan.get("id") == self.current_scan_id:
                continue
            # Look for scans that are pending (not yet started)
            if scan.get("status") == "pending":
                return scan
        return None
