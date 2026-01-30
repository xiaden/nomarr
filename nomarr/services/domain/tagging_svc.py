"""Tagging service - applies calibrated tags to library files."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.calibration_dto import (
    WriteCalibratedTagsParams,
)
from nomarr.helpers.dto.library_dto import ReconcileTagsResult
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService


logger = logging.getLogger(__name__)


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

    def __init__(self, database: Database, library_service: LibraryService | None = None) -> None:
        """Initialize the tagging service.

        Args:
            database: Database instance for persistence operations
            library_service: LibraryService instance (optional, for library operations)

        """
        self.db = database
        self.library_service = library_service

    @property
    def namespace(self) -> str:
        """Get the tag namespace from library service config."""
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot determine namespace."
            raise ValueError(msg)
        return self.library_service.cfg.namespace

    def tag_file(
        self,
        file_path: str,
        models_dir: str,
        namespace: str,
        version_tag_key: str,
        calibrate_heads: bool,
    ) -> None:
        """Write calibrated tags to a single file.

        Args:
            file_path: Absolute path to the audio file
            models_dir: Path to models directory
            namespace: Tag namespace (e.g., "nom")
            version_tag_key: Metadata key for version tracking
            calibrate_heads: Whether to use calibration

        Raises:
            ValueError: If file doesn't have existing tags

        """

        from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf

        logger.info(f"Writing calibrated tags to file: {file_path}")

        params = WriteCalibratedTagsParams(
            file_path=file_path,
            models_dir=models_dir,
            namespace=namespace,
            version_tag_key=version_tag_key,
            calibrate_heads=calibrate_heads,
        )

        write_calibrated_tags_wf(db=self.db, params=params)
        logger.info(f"Wrote calibrated tags: {file_path}")

    def tag_library(
        self,
        models_dir: str,
        namespace: str,
        version_tag_key: str,
        calibrate_heads: bool,
    ) -> ApplyCalibrationResult:
        """Write calibrated tags to all TAGGED library files.

        This requires files that already have numeric tags in the database.
        It applies calibration to existing raw scores without re-running ML inference.

        Args:
            models_dir: Path to models directory
            namespace: Tag namespace (e.g., "nom")
            version_tag_key: Metadata key for version tracking
            calibrate_heads: Whether to use calibration

        Returns:
            ApplyCalibrationResult with processed count and message

        Raises:
            ValueError: If library_service not configured

        """
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot get library paths."
            raise ValueError(msg)

        # Get only TAGGED library file paths (needs existing tags)
        paths = self.library_service.get_tagged_library_paths()

        if not paths:
            return ApplyCalibrationResult(
                queued=0,  # Keep field name for DTO compatibility
                message="No tagged files found. Run tagging first.",
            )

        logger.info(f"Writing calibrated tags to {len(paths)} files...")

        from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf

        success_count = 0
        for file_path in paths:
            try:
                params = WriteCalibratedTagsParams(
                    file_path=file_path,
                    models_dir=models_dir,
                    namespace=namespace,
                    version_tag_key=version_tag_key,
                    calibrate_heads=calibrate_heads,
                )
                write_calibrated_tags_wf(db=self.db, params=params)
                success_count += 1
            except Exception as e:
                logger.warning(f"Failed to write calibrated tags for {file_path}: {e}")

        logger.info(f"Wrote calibrated tags: {success_count}/{len(paths)} files")

        return ApplyCalibrationResult(
            queued=success_count,  # Keep field name for DTO compatibility
            message=f"Wrote calibrated tags to {success_count}/{len(paths)} files",
        )

    def get_calibration_status(self) -> dict[str, Any]:
        """Get global calibration status with per-library breakdown.

        Returns:
            Dict representation of GlobalCalibrationStatus DTO

        """
        from nomarr.helpers.dto.calibration_dto import (
            GlobalCalibrationStatus,
            LibraryCalibrationStatus,
        )

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
