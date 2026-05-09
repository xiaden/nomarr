"""Library scanning operations.

This module handles:
- Starting and cancelling scans
- Scan status and history
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library import (
    get_library_scan_histories,
    resolve_library_for_scan,
)
from nomarr.components.library.scan_lifecycle_comp import (
    _pipeline_state_to_scan_status,
    get_pipeline_state,
    get_scan_state,
    on_scan_complete_pipeline_hook,
)
from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.library_dto import LibraryScanStatusResult, StartScanResult
from nomarr.services.infrastructure.config_svc import INTERNAL_MIN_DURATION_S
from nomarr.workflows.library.scan_library_full_wf import scan_library_full_workflow
from nomarr.workflows.library.scan_library_quick_wf import scan_library_quick_workflow
from nomarr.workflows.library.scan_setup_wf import scan_setup_workflow
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

    def start_quick_scan(self, library_id: str) -> StartScanResult:
        """Start a quick (incremental) library scan.

        Validates the library synchronously then dispatches the scan as a
        background task.

        Args:
            library_id: ID of the library to scan

        Returns:
            StartScanResult DTO with scan statistics and task_id

        Raises:
            LibraryNotFoundError: If library not found
            LibraryAlreadyScanningError: If library is already being scanned

        """
        scan_setup_workflow(self.db, library_id, scan_type="quick")
        task_id = f"scan_library_{library_id}"
        on_complete = functools.partial(on_scan_complete_pipeline_hook, self.db, library_id)
        if self.background_tasks is None:
            msg = "Background task service is not available"
            raise RuntimeError(msg)
        task = ManagedTask(
            task_id=task_id,
            fn=functools.partial(
                scan_library_quick_workflow,
                db=self.db,
                library_id=library_id,
                tagger_version=self.cfg.tagger_version,
                min_duration_s=INTERNAL_MIN_DURATION_S,
            ),
            on_complete=on_complete,
            daemon=True,
        )
        self.background_tasks.start_task(task)
        return StartScanResult(
            files_discovered=0,
            files_queued=0,
            files_skipped=0,
            files_removed=0,
            job_ids=[task_id],
        )

    def start_full_scan(self, library_id: str) -> StartScanResult:
        """Start a full library scan.

        Validates the library synchronously then dispatches the scan as a
        background task.

        Args:
            library_id: ID of the library to scan

        Returns:
            StartScanResult DTO with scan statistics and task_id

        Raises:
            LibraryNotFoundError: If library not found
            LibraryAlreadyScanningError: If library is already being scanned

        """
        scan_setup_workflow(self.db, library_id, scan_type="full")
        task_id = f"scan_library_{library_id}"
        on_complete = functools.partial(on_scan_complete_pipeline_hook, self.db, library_id)
        if self.background_tasks is None:
            msg = "Background task service is not available"
            raise RuntimeError(msg)
        task = ManagedTask(
            task_id=task_id,
            fn=functools.partial(
                scan_library_full_workflow,
                db=self.db,
                library_id=library_id,
                tagger_version=self.cfg.tagger_version,
                models_dir=self.cfg.models_dir,
                namespace=self.cfg.namespace,
                min_duration_s=INTERNAL_MIN_DURATION_S,
            ),
            on_complete=on_complete,
            daemon=True,
        )
        self.background_tasks.start_task(task)
        return StartScanResult(
            files_discovered=0,
            files_queued=0,
            files_skipped=0,
            files_removed=0,
            job_ids=[task_id],
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
            )
        if library_id is None:
            return LibraryScanStatusResult(
                configured=True,
                library_path=self.cfg.library_root,
                enabled=self.background_tasks is not None,
            )
        resolve_library_for_scan(self.db, library_id)  # Validate library exists
        scan_state = get_scan_state(self.db, library_id)
        try:
            pipeline_state = get_pipeline_state(self.db, library_id)
        except ValueError:
            pipeline_state = None
        scan_status = _pipeline_state_to_scan_status(pipeline_state, scan_state)
        scan_progress = 0 if scan_state is None else int(scan_state.get("files_processed", 0) or 0)
        scan_total = 0 if scan_state is None else int(scan_state.get("files_total", 0) or 0)
        scanned_at = None if scan_state is None else scan_state.get("completed_at")
        scan_error = None if scan_state is None else scan_state.get("error")
        enabled = self.background_tasks is not None
        return LibraryScanStatusResult(
            configured=True,
            library_path=self.cfg.library_root,
            enabled=enabled,
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
        return get_library_scan_histories(self.db, limit=limit)

    def validate_library_tags(
        self,
        library_id: str,
        auto_repair: bool = True,
    ) -> dict[str, Any]:
        """Validate tag completeness for files in a library.

        Checks that every file marked as tagged has edges for all discovered
        ML heads.  Incomplete files are optionally repaired by marking them
        back to the ``not_tagged`` state so discovery workers reprocess them.

        Args:
            library_id: Library to validate
            auto_repair: If True, mark incomplete files for re-tagging

        Returns:
            Validation summary dict (files_checked, incomplete_files, etc.)

        """
        resolve_library_for_scan(self.db, library_id)
        return validate_library_tags_workflow(
            db=self.db,
            models_dir=self.cfg.models_dir,
            library_id=library_id,
            namespace=self.cfg.namespace,
            auto_repair=auto_repair,
        )
