"""Recalibration service - applies calibration to existing library files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService


logger = logging.getLogger(__name__)


class RecalibrationService:
    """Service for recalibrating library files with updated calibration values.

    This service provides methods to recalibrate files with new calibration values.
    Recalibration updates tier and mood tags by applying calibration to raw scores
    already stored in the database, without re-running ML inference.

    Architecture note:
    - Service provides API surface and DI
    - Actual recalibration logic lives in workflows/calibration/recalibrate_file_wf.py
    - Threading/background execution should be in workflow layer, not service layer
    """

    def __init__(self, database: Database, library_service: LibraryService | None = None):
        """Initialize the recalibration service.

        Args:
            database: Database instance for persistence operations
            library_service: LibraryService instance (optional, for library operations)
        """
        self.db = database
        self.library_service = library_service

    def recalibrate_file(
        self,
        file_path: str,
        models_dir: str,
        namespace: str,
        version_tag_key: str,
        calibrate_heads: bool,
    ) -> None:
        """Recalibrate a single file with updated calibration values.

        Args:
            file_path: Absolute path to the audio file
            models_dir: Path to models directory
            namespace: Tag namespace (e.g., "nom")
            version_tag_key: Metadata key for version tracking
            calibrate_heads: Whether to use calibration

        Raises:
            ValueError: If file doesn't have existing tags to recalibrate
        """
        from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
        from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

        logger.info(f"Recalibrating file: {file_path}")

        params = RecalibrateFileWorkflowParams(
            file_path=file_path,
            models_dir=models_dir,
            namespace=namespace,
            version_tag_key=version_tag_key,
            calibrate_heads=calibrate_heads,
        )

        recalibrate_file_workflow(db=self.db, params=params)
        logger.info(f"Recalibration complete: {file_path}")

    def recalibrate_library(
        self,
        models_dir: str,
        namespace: str,
        version_tag_key: str,
        calibrate_heads: bool,
    ) -> ApplyCalibrationResult:
        """Recalibrate all TAGGED library files with updated calibration values.

        Recalibration requires files that already have numeric tags in the database.
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
            raise ValueError("LibraryService not configured. Cannot get library paths.")

        # Get only TAGGED library file paths (recalibration needs existing tags)
        paths = self.library_service.get_tagged_library_paths()

        if not paths:
            return ApplyCalibrationResult(
                queued=0,  # Keep field name for DTO compatibility
                message="No tagged files found. Run tagging first.",
            )

        logger.info(f"Recalibrating {len(paths)} tagged files...")

        from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
        from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

        success_count = 0
        for file_path in paths:
            try:
                params = RecalibrateFileWorkflowParams(
                    file_path=file_path,
                    models_dir=models_dir,
                    namespace=namespace,
                    version_tag_key=version_tag_key,
                    calibrate_heads=calibrate_heads,
                )
                recalibrate_file_workflow(db=self.db, params=params)
                success_count += 1
            except Exception as e:
                logger.warning(f"Failed to recalibrate {file_path}: {e}")

        logger.info(f"Recalibration complete: {success_count}/{len(paths)} files")

        return ApplyCalibrationResult(
            queued=success_count,  # Keep field name for DTO compatibility
            message=f"Recalibrated {success_count}/{len(paths)} tagged files",
        )

    def get_calibration_status(self) -> dict[str, Any]:
        """Get global calibration status with per-library breakdown.

        Returns:
            Dict representation of GlobalCalibrationStatus DTO
        """
        from dataclasses import asdict

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
                        )
                    )

        result = GlobalCalibrationStatus(
            global_version=global_version,
            last_run=last_run,
            libraries=library_status_list,
        )

        # Convert to dict for interface layer
        result_dict: dict[str, Any] = asdict(result)
        return result_dict
