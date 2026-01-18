"""Library scanning operations.

This module handles:
- Starting and cancelling scans
- Scan status and history
- Worker health checks for scanning
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.queue import list_jobs as list_jobs_component
from nomarr.helpers.dto.library_dto import LibraryScanStatusResult, ScanTarget, StartScanResult
from nomarr.helpers.dto.queue_dto import Job

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryScanMixin:
    """Mixin providing library scanning methods."""

    db: Database
    cfg: LibraryServiceConfig
    background_tasks: Any | None

    def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
        """Get a library by ID or raise an error."""
        # This method is defined in admin.py mixin, but we reference it here
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return library

    def _has_healthy_library_workers(self) -> bool:
        """
        Check if any library workers are healthy and available.

        Returns:
            True if at least one library worker has a recent heartbeat
        """
        workers = self.db.health.get_all_workers()

        for worker in workers:
            component = worker.get("component")
            if not isinstance(component, str) or not component.startswith("worker:library:"):
                continue

            # Check if worker is healthy (heartbeat within 30 seconds)
            from nomarr.helpers.time_helper import now_ms

            health = self.db.health.get_component(component)
            if health and health.get("status") == "healthy":
                last_heartbeat = health.get("last_heartbeat", 0)
                if now_ms() - last_heartbeat < 30_000:  # 30 seconds
                    return True

        return False

    def _is_scan_running(self) -> bool:
        """
        Check if any scan jobs are currently being processed.

        Returns:
            True if any jobs are in 'running' status
        """
        # Query for any running scan jobs using component
        jobs_list, _ = list_jobs_component(self.db, queue_type="library", limit=1000)
        return any(job["status"] == "running" for job in jobs_list)

    def scan_targets(
        self,
        targets: list[ScanTarget],
        batch_size: int = 200,
        force_rescan: bool = False,
    ) -> StartScanResult:
        """
        Scan specific folders within libraries.

        This is the core scanning method that supports both full library scans
        and targeted/incremental scans. Use this when you want fine-grained control
        over which folders to scan.

        Args:
            targets: List of ScanTarget specifying which folders to scan.
                     Each target identifies a library and optional subfolder.
                     Empty folder_path means scan entire library.
            batch_size: Number of files to batch per database write (default: 200)
            force_rescan: If True, skip unchanged files detection (rescan all files)

        Returns:
            StartScanResult DTO with scan statistics and task_id

        Raises:
            ValueError: If targets list is empty
            ValueError: If any library_id not found
            ValueError: If scan already running for any target library
            ValueError: If multiple targets reference the same library
        """
        from nomarr.workflows.library.start_scan_wf import start_scan_workflow

        # Validation: targets must not be empty
        if not targets:
            raise ValueError("Cannot scan: targets list is empty")

        # Validation: check for duplicate library_ids in targets
        library_ids = [t.library_id for t in targets]
        if len(library_ids) != len(set(library_ids)):
            raise ValueError("Cannot scan: multiple targets reference the same library")

        # Validation: ensure all libraries exist
        for target in targets:
            self._get_library_or_error(target.library_id)

        # Use first target's library_id for orchestration
        # (start_scan_workflow expects a primary library_id)
        primary_library_id = targets[0].library_id

        return start_scan_workflow(
            db=self.db,
            background_tasks=self.background_tasks,
            library_id=primary_library_id,
            scan_targets=targets,
            batch_size=batch_size,
            force_rescan=force_rescan,
        )

    def start_scan_for_library(
        self,
        library_id: str,
        force_rescan: bool = False,
    ) -> StartScanResult:
        """
        Start a full library scan for a specific library.

        This is a convenience method that delegates to scan_targets()
        with a full library scan target (empty folder_path).

        Scans the entire library root recursively and marks missing files as invalid.

        IMPORTANT: Libraries are used ONLY to determine which filesystem roots to scan.
        All discovered files and statistics remain GLOBAL and do NOT track library_id.
        Nomarr is an autotagger, not a multi-tenant library manager.

        Args:
            library_id: ID of the library to scan
            force_rescan: If True, skip unchanged files detection (rescan all files)

        Returns:
            StartScanResult DTO with scan statistics and task_id

        Raises:
            ValueError: If library not found or scan already running
        """
        # Delegate to scan_targets with full library scan
        target = ScanTarget(library_id=library_id, folder_path="")
        return self.scan_targets([target], force_rescan=force_rescan)

    def start_scan(
        self,
        library_id: str | None = None,
    ) -> StartScanResult:
        """
        Start a library scan.

        Scans the entire library root recursively and marks missing files as invalid.

        This is the main scanning entrypoint. It delegates to the workflow,
        which resolves the library (specified or default) and handles orchestration.

        IMPORTANT: Libraries are used ONLY to pick which filesystem roots to scan.
        All discovered files and stats are GLOBAL and do NOT carry library_id.

        Args:
            library_id: ID of library to scan (defaults to default library)

        Returns:
            StartScanResult DTO with scan statistics

        Raises:
            ValueError: If library not found or no default library exists
        """
        from nomarr.workflows.library.start_scan_wf import start_scan_workflow

        return start_scan_workflow(
            db=self.db,
            background_tasks=self.background_tasks,
            library_id=library_id,
        )

    def cancel_scan(self, library_id: str | None = None) -> bool:
        """
        Cancel the currently running scan.

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
            raise ValueError("Library scanning not configured")

        # TODO: Implement scan cancellation for BackgroundTaskService
        # For now, scans run to completion
        logging.warning("[LibraryService] Scan cancellation not yet implemented for direct scans")
        return False

    def get_status(self, library_id: str | None = None) -> LibraryScanStatusResult:
        """
        Get current library scan status.

        Args:
            library_id: Optional library ID to check scan status for (uses default if None)

        Returns:
            LibraryScanStatusResult with configured, library_path, enabled, scan_status, progress, total
        """
        if not self.cfg.library_root:
            return LibraryScanStatusResult(
                configured=False,
                library_path=None,
                enabled=False,
                pending_jobs=0,  # Legacy field
                running_jobs=0,  # Legacy field
            )

        # Get library to check scan status
        if library_id is None:
            try:
                library = self.db.libraries.get_default_library()
                if not library:
                    return LibraryScanStatusResult(
                        configured=True,
                        library_path=self.cfg.library_root,
                        enabled=False,
                        pending_jobs=0,
                        running_jobs=0,
                    )
                library_id = library["_id"]
            except Exception:
                return LibraryScanStatusResult(
                    configured=True,
                    library_path=self.cfg.library_root,
                    enabled=False,
                    pending_jobs=0,
                    running_jobs=0,
                )
        else:
            library = self._get_library_or_error(library_id)

        # Check scan status from library record
        scan_status = library.get("scan_status", "idle")
        scan_progress = library.get("scan_progress", 0)
        scan_total = library.get("scan_total", 0)
        scanned_at = library.get("scanned_at")
        scan_error = library.get("scan_error")

        # Determine if scanning is enabled (background tasks available)
        enabled = self.background_tasks is not None

        return LibraryScanStatusResult(
            configured=True,
            library_path=self.cfg.library_root,
            enabled=enabled,
            pending_jobs=0,  # Legacy field (no queue)
            running_jobs=1 if scan_status == "scanning" else 0,  # Legacy field
            scan_status=scan_status,
            scan_progress=scan_progress,
            scan_total=scan_total,
            scanned_at=scanned_at,
            scan_error=scan_error,
        )

    def get_scan_history(self, limit: int = 100) -> list[Job]:
        """
        Get recent library scan jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of Job DTOs
        """
        from nomarr.services.domain._library_mapping import map_queue_job_to_dto

        jobs_list, _ = list_jobs_component(self.db, queue_type="library", limit=limit)
        return [map_queue_job_to_dto(job) for job in jobs_list]
