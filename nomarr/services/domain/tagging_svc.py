"""Tagging service - applies calibrated tags to library files."""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.calibration_dto import (
    GlobalCalibrationStatus,
    LibraryCalibrationStatus,
    WriteCalibratedTagsParams,
)
from nomarr.helpers.dto.library_dto import ReconcileTagsResult
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
from nomarr.workflows.calibration.apply_calibration_wf import apply_calibration_wf
from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService


logger = logging.getLogger(__name__)


@dataclass
class TaggingServiceConfig:
    """Configuration for TaggingService.

    Attributes:
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking
        calibrate_heads: Whether to apply calibration heads

    """

    models_dir: str
    namespace: str
    version_tag_key: str
    calibrate_heads: bool = False


class TaggingService:
    """Service for writing calibrated tags to library files.

    This service provides methods to apply calibration to files.
    It updates tier and mood tags by applying calibration to raw scores
    already stored in the database, without re-running ML inference.

    Architecture note:
    - Service provides API surface and DI
    - Actual tagging logic lives in workflows/calibration/write_calibrated_tags_wf.py
    - Threading/background execution should be in workflow layer, not service layer
    """

    def __init__(
        self,
        database: Database,
        cfg: TaggingServiceConfig,
        library_service: LibraryService | None = None,
    ) -> None:
        """Initialize the tagging service.

        Args:
            database: Database instance for persistence operations
            cfg: Service configuration (models_dir, namespace, etc.)
            library_service: LibraryService instance (optional, for library operations)

        """
        self.db = database
        self.cfg = cfg
        self.library_service = library_service

        # Background apply state — explicit lifecycle: idle → running → completed/failed
        self._apply_thread: threading.Thread | None = None
        self._apply_result: ApplyCalibrationResult | None = None
        self._apply_error: Exception | None = None
        self._apply_progress_lock = threading.Lock()
        self._apply_progress: dict[str, Any] = {}

    @property
    def namespace(self) -> str:
        """Get the tag namespace from library service config."""
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot determine namespace."
            raise ValueError(msg)
        return self.library_service.cfg.namespace

    def tag_file(self, file_path: str) -> None:
        """Write calibrated tags to a single file.

        Args:
            file_path: Absolute path to the audio file

        """
        params = WriteCalibratedTagsParams(
            file_path=file_path,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self.cfg.calibrate_heads,
        )

        write_calibrated_tags_wf(db=self.db, params=params)
        logger.info(f"Wrote calibrated tags: {file_path}")

    def tag_library(self) -> ApplyCalibrationResult:
        """Write calibrated tags to all TAGGED library files.

        Delegates to apply_calibration_wf for the actual iteration.
        Progress updates are forwarded via self._update_apply_progress.

        Returns:
            ApplyCalibrationResult with processed/failed counts

        Raises:
            ValueError: If library_service not configured

        """
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot get library paths."
            raise ValueError(msg)

        # Get only TAGGED library file paths (needs existing tags)
        paths = self.library_service.get_tagged_library_paths()

        return apply_calibration_wf(
            db=self.db,
            paths=paths,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self.cfg.calibrate_heads,
            on_progress=self._update_apply_progress,
        )

    # -- Background apply threading infrastructure --

    def start_apply_calibration_background(self) -> None:
        """Start calibration apply in background thread.

        Non-blocking: returns immediately. Poll with is_apply_running() and
        get_apply_status() / get_apply_progress().

        Uses configuration from TaggingServiceConfig for models_dir, namespace, etc.

        Note: Single-process only. Thread state is in-memory and will not survive
        worker restarts, multiple uvicorn workers, or horizontal scaling.

        """
        if self._apply_thread and self._apply_thread.is_alive():
            logger.warning("[TaggingService] Apply already running")
            return

        # Reset state for new run (clears previous completed/failed state)
        self._apply_result = None
        self._apply_error = None
        self._clear_apply_progress()

        # Start background thread
        self._apply_thread = threading.Thread(
            target=self._run_apply_calibration,
            name="CalibrationApply",
            daemon=False,
        )
        self._apply_thread.start()
        logger.info("[TaggingService] Started calibration apply in background")

    def _run_apply_calibration(self) -> None:
        """Background thread: run calibration apply.

        Progress is NOT cleared on completion — the final snapshot remains queryable
        until the next run starts.
        """
        try:
            logger.info("[TaggingService] Background apply started")
            result = self.tag_library()
            self._apply_result = result
            logger.info(
                f"[TaggingService] Background apply completed: "
                f"{result.processed} processed, {result.failed} failed out of {result.total}",
            )
        except Exception as e:
            logger.error(f"[TaggingService] Background apply failed: {e}", exc_info=True)
            self._apply_error = e

    def _update_apply_progress(self, **kwargs: int | str | None) -> None:
        """Thread-safe update of apply progress state.

        Args:
            **kwargs: Progress fields to update. Valid keys:
                completed_files, total_files, current_file

        """
        with self._apply_progress_lock:
            self._apply_progress.update(kwargs)

    def _clear_apply_progress(self) -> None:
        """Reset apply progress state."""
        with self._apply_progress_lock:
            self._apply_progress = {}

    def is_apply_running(self) -> bool:
        """Check if calibration apply is currently running."""
        return self._apply_thread is not None and self._apply_thread.is_alive()

    def get_apply_status(self) -> dict[str, Any]:
        """Get current status of background calibration apply.

        Lifecycle: idle → running → completed | failed.
        Status remains queryable after completion until next start clears it.

        Returns:
            {
              "status": "idle" | "running" | "completed" | "failed",
              "result": {"processed": int, "failed": int, "total": int, "message": str} | None,
              "error": str | None,
            }

        """
        running = self.is_apply_running()

        if running:
            status = "running"
        elif self._apply_error:
            status = "failed"
        elif self._apply_result:
            status = "completed"
        else:
            status = "idle"

        error = str(self._apply_error) if self._apply_error else None
        result_dict = None
        if self._apply_result:
            result_dict = {
                "processed": self._apply_result.processed,
                "failed": self._apply_result.failed,
                "total": self._apply_result.total,
                "message": self._apply_result.message,
            }

        return {
            "status": status,
            "result": result_dict,
            "error": error,
        }

    def get_apply_progress(self) -> dict[str, Any]:
        """Get calibration apply progress.

        Progress snapshot persists after completion until next run.

        Returns:
            {
              "total_files": int,
              "completed_files": int,
              "current_file": str | None,
              "is_running": bool,
            }

        """
        running = self.is_apply_running()
        with self._apply_progress_lock:
            progress = dict(self._apply_progress)

        return {
            "total_files": progress.get("total_files", 0),
            "completed_files": progress.get("completed_files", 0),
            "current_file": progress.get("current_file"),
            "is_running": running,
        }

    def get_calibration_status(self) -> dict[str, Any]:
        """Get global calibration status with per-library breakdown.

        Returns:
            Dict representation of GlobalCalibrationStatus DTO

        """
        # Get global calibration version from meta
        global_version = self.db.meta.get("calibration_version")
        last_run_str = self.db.meta.get("calibration_last_run")
        last_run = int(last_run_str) if last_run_str else None

        # Get per-library calibration counts
        library_status_list = []
        if global_version and self.library_service:
            # Get library counts
            status_data = self.db.library_files.get_calibration_status_by_library(global_version)

            # Enrich with library names
            for status in status_data:
                library_id = status["library_id"]
                library_doc = self.db.libraries.get_library(library_id)

                if library_doc:
                    total = status["total_files"]
                    current = status["current_count"]
                    outdated = status["outdated_count"]
                    percentage = (current / total * 100) if total > 0 else 0.0

                    library_status_list.append(
                        LibraryCalibrationStatus(
                            library_id=library_id,
                            library_name=library_doc.get("name", "Unknown"),
                            total_files=total,
                            current_count=current,
                            outdated_count=outdated,
                            percentage=round(percentage, 1),
                        ),
                    )

        result = GlobalCalibrationStatus(
            global_version=global_version,
            last_run=last_run,
            libraries=library_status_list,
        )

        # Convert to dict for interface layer
        result_dict: dict[str, Any] = asdict(result)
        return result_dict

    def read_file_tags(self, path: str, namespace: str) -> dict[str, Any]:
        """Read tags from an audio file.

        Args:
            path: Absolute file path
            namespace: Tag namespace to filter by

        Returns:
            Dictionary of tag_key -> value(s)

        Raises:
            ValueError: If path is invalid
            RuntimeError: If file cannot be read

        """
        return read_file_tags_workflow(db=self.db, path=path, namespace=namespace)

    def remove_file_tags(self, path: str, namespace: str) -> int:
        """Remove all namespaced tags from an audio file.

        Args:
            path: Absolute file path
            namespace: Tag namespace to remove

        Returns:
            Number of tags removed

        Raises:
            ValueError: If path is invalid
            RuntimeError: If file cannot be modified

        """
        return remove_file_tags_workflow(db=self.db, path=path, namespace=namespace)

    def reconcile_library(
        self,
        library_id: str,
        batch_size: int = 100,
        namespace: str = "nom",
    ) -> ReconcileTagsResult:
        """Reconcile file tags for a library based on its file_write_mode.

        Claims files with mismatched projection state and writes tags according
        to the library's current mode and calibration. This handles:
        - Mode changes (e.g., switching from "full" to "minimal")
        - Calibration updates (new mood tag values)
        - New ML results (files analyzed but never written)

        Args:
            library_id: Library document _id
            batch_size: Number of files to process per batch
            namespace: Tag namespace (default: "nom")

        Returns:
            ReconcileTagsResult with processed, remaining, and failed counts

        """
        # Get library settings
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        target_mode = library.get("file_write_mode", "full")

        # Get current calibration hash
        calibration_hash = self.db.meta.get("calibration_version")
        has_calibration = bool(calibration_hash)

        # Claim files for reconciliation
        worker_id = f"reconcile:{library_id}"
        claimed_files = self.db.library_files.claim_files_for_reconciliation(
            library_id=library_id,
            target_mode=target_mode,
            calibration_hash=calibration_hash,
            worker_id=worker_id,
            batch_size=batch_size,
        )

        processed = 0
        failed = 0

        for file_doc in claimed_files:
            file_key = file_doc["_key"]
            try:
                result = write_file_tags_workflow(
                    db=self.db,
                    file_key=file_key,
                    target_mode=target_mode,
                    calibration_hash=calibration_hash,
                    has_calibration=has_calibration,
                    namespace=namespace,
                )
                if result.success:
                    processed += 1
                else:
                    failed += 1
                    logger.warning(f"[reconcile] Failed to write tags for {file_key}: {result.error}")
            except Exception as e:
                failed += 1
                logger.exception(f"[reconcile] Error processing {file_key}: {e}")
                # Release claim on error
                try:
                    self.db.library_files.release_claim(file_key)
                except Exception as release_err:
                    logger.debug(f"[reconcile] Failed to release claim for {file_key}: {release_err}")

        # Count remaining files needing reconciliation
        remaining = self.db.library_files.count_files_needing_reconciliation(
            library_id=library_id,
            target_mode=target_mode,
            calibration_hash=calibration_hash,
        )

        logger.info(f"[reconcile] Library {library_id}: processed={processed}, failed={failed}, remaining={remaining}")

        return ReconcileTagsResult(
            processed=processed,
            remaining=remaining,
            failed=failed,
        )

    def get_reconcile_status(
        self,
        library_id: str,
    ) -> dict[str, Any]:
        """Get reconciliation status for a library.

        Args:
            library_id: Library document _id

        Returns:
            Dict with pending_count and in_progress status

        """
        # Get library settings
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        target_mode = library.get("file_write_mode", "full")
        calibration_hash = self.db.meta.get("calibration_version")

        pending_count = self.db.library_files.count_files_needing_reconciliation(
            library_id=library_id,
            target_mode=target_mode,
            calibration_hash=calibration_hash,
        )

        # For now, in_progress is always False (sync reconciliation)
        # Can be extended later for background task tracking
        return {
            "pending_count": pending_count,
            "in_progress": False,
        }
