"""Library scanning operations.

This module handles:
- Starting and cancelling scans
- Scan status and history
- Worker health checks for scanning
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from nomarr.helpers.dto.library_dto import LibraryScanStatusResult, StartScanResult
from nomarr.helpers.time_helper import now_ms
from nomarr.workflows.library.start_library_scan_wf import start_library_scan_workflow
from nomarr.workflows.library.validate_library_tags_wf import validate_library_tags_workflow

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryScanMixin:
    """Mixin providing library scanning methods."""

    cfg: LibraryServiceConfig
    db: Database
    background_tasks: Any | None

    def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
        """Get a library by ID or raise an error."""
        result = self.db.libraries.get_library(library_id)
        if result is None:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)
        return result

    def _has_healthy_library_workers(self) -> bool:
        """Check if any library workers are healthy and available.

        Returns:
            True if at least one library worker has a recent heartbeat

        """
        workers = self.db.health.get_all_workers()
        for worker in workers:
            component = worker.get("component")
            if not isinstance(component, str) or not component.startswith("worker:library:"):
                continue
            health = self.db.health.get_component(component)
            if health and health.get("status") == "healthy":
                last_heartbeat = health.get("last_heartbeat", 0)
                if now_ms().value - last_heartbeat < 30000:
                    return True
        return False

    def _is_scan_running(self) -> bool:
        """Check if any scan is currently running.

        Uses library.scan_status field instead of queue jobs.

        Returns:
            True if any library has scan_status='scanning'

        """
        libraries = self.db.libraries.list_libraries(enabled_only=False)
        return any(lib.get("scan_status") == "scanning" for lib in libraries)

    def start_scan_for_library(
        self,
        library_id: str,
        scan_type: Literal["quick", "full"] = "quick",
    ) -> StartScanResult:
        """Start a library scan.

        Args:
            library_id: ID of the library to scan
            scan_type: ``"quick"`` (incremental) or ``"full"`` (rescan all)

        Returns:
            StartScanResult DTO with scan statistics and task_id

        Raises:
            ValueError: If library not found, already scanning, or invalid scan_type

        """
        return start_library_scan_workflow(
            db=self.db,
            background_tasks=self.background_tasks,
            tagger_version=self.cfg.tagger_version,
            library_id=library_id,
            scan_type=scan_type,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
        )

    def cancel_scan(self, library_id: str | None = None) -> bool:
        """Cancel the currently running scan.

        Note: Cancellation support not yet implemented for direct scans.
        This method is kept for API compatibility but currently returns False.

        Args:
            library_id: Optional library ID (uses default if None)

        Returns:
            False (cancellation not yet supported)

        Raises:
            ValueError: If library not configured

        """
        if not self.cfg.library_root:
            msg = "Library scanning not configured"
            raise ValueError(msg)
        logger.warning("[LibraryService] Scan cancellation not yet implemented for direct scans")
        return False

    def get_status(self, library_id: str | None = None) -> LibraryScanStatusResult:
        """Get current library scan status.

        Args:
            library_id: Library ID to check scan status for

        Returns:
            LibraryScanStatusResult with configured, library_path, enabled, scan_status, progress, total

        """
        if not self.cfg.library_root:
            return LibraryScanStatusResult(
                configured=False,
                library_path=None,
                enabled=False,
                pending_jobs=0,
                running_jobs=0,
            )
        if library_id is None:
            return LibraryScanStatusResult(
                configured=True,
                library_path=self.cfg.library_root,
                enabled=self.background_tasks is not None,
                pending_jobs=0,
                running_jobs=0,
            )
        library = self._get_library_or_error(library_id)
        scan_status = library.get("scan_status", "idle")
        scan_progress = library.get("scan_progress", 0)
        scan_total = library.get("scan_total", 0)
        scanned_at = library.get("scanned_at")
        scan_error = library.get("scan_error")
        enabled = self.background_tasks is not None
        return LibraryScanStatusResult(
            configured=True,
            library_path=self.cfg.library_root,
            enabled=enabled,
            pending_jobs=0,
            running_jobs=1 if scan_status == "scanning" else 0,
            scan_status=scan_status,
            scan_progress=scan_progress,
            scan_total=scan_total,
            scanned_at=scanned_at,
            scan_error=scan_error,
        )

    def get_scan_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent library scan history from library records.

        Note: Queue-based job history removed in favor of library.scanned_at field.
        Returns simplified scan info from library records.

        Args:
            limit: Maximum number of libraries to return

        Returns:
            List of scan info dicts with library_id, name, scanned_at, scan_status

        """
        libraries = self.db.libraries.list_libraries(enabled_only=False)
        return [
            {
                "library_id": lib["_id"],
                "name": lib.get("name", "Unknown"),
                "scanned_at": lib.get("scanned_at"),
                "scan_status": lib.get("scan_status", "idle"),
            }
            for lib in libraries[:limit]
        ]

    def validate_library_tags(
        self,
        library_id: str,
        auto_repair: bool = True,
    ) -> dict[str, Any]:
        """Validate tag completeness for files in a library.

        Checks that every file marked as tagged has edges for all discovered
        ML heads.  Incomplete files are optionally repaired by marking them
        ``needs_tagging=true`` so the next scan reprocesses them.

        Args:
            library_id: Library to validate
            auto_repair: If True, mark incomplete files for re-tagging

        Returns:
            Validation summary dict (files_checked, incomplete_files, etc.)

        """
        self._get_library_or_error(library_id)
        return validate_library_tags_workflow(
            db=self.db,
            models_dir=self.cfg.models_dir,
            library_id=library_id,
            namespace=self.cfg.namespace,
            auto_repair=auto_repair,
        )
