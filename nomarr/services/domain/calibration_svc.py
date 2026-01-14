"""
CalibrationService - Thin orchestration wrapper for calibration generation workflow.

This service delegates to workflows.calibration_generation for the actual calibration logic.
It provides dependency injection (db, models_dir, namespace, thresholds) from the application
context to the pure workflow function.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.admin_dto import CalibrationHistoryResult, RunCalibrationResult
from nomarr.helpers.dto.calibration_dto import CalibrationRunResult, GenerateCalibrationResult
from nomarr.helpers.dto.recalibration_dto import GenerateCalibrationResult as GenerateCalibrationResultWrapper
from nomarr.workflows.calibration.generate_calibration_wf import generate_calibration_workflow

if TYPE_CHECKING:
    from nomarr.helpers.dto.ml_dto import GenerateMinmaxCalibrationResult, SaveCalibrationSidecarsResult
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


@dataclass
class CalibrationConfig:
    """Configuration for CalibrationService."""

    models_dir: str
    namespace: str
    thresholds: dict[str, float] = field(default_factory=dict)
    calibrate_heads: bool = False  # Whether calibration features are enabled


class CalibrationService:
    """
    Service for orchestrating calibration generation.

    Thin wrapper that provides DI to the calibration workflow.
    All domain logic lives in workflows.calibration_generation.
    """

    def __init__(
        self,
        db: Database,
        cfg: CalibrationConfig,
    ):
        """
        Initialize calibration service.

        Args:
            db: Database instance
            cfg: Calibration configuration
        """
        self._db = db
        self.cfg = cfg

    def generate_calibration_with_tracking(self) -> GenerateCalibrationResult:
        """
        Generate calibrations for all heads and track drift metrics.

        Delegates to workflows.calibration_generation.generate_calibration_workflow.

        Returns:
            GenerateCalibrationResult DTO with version, library_size, heads, saved_files, reference_updates, summary
        """
        logger.debug("[CalibrationService] Delegating to calibration generation workflow")

        return generate_calibration_workflow(
            db=self._db,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            thresholds=self.cfg.thresholds,
        )

    def generate_minmax_calibration(self) -> GenerateMinmaxCalibrationResult:
        """
        Generate minmax calibration data from database tags.

        Returns:
            Calibration data DTO with min/max values per head
        """
        from nomarr.components.ml.ml_calibration_comp import generate_minmax_calibration

        return generate_minmax_calibration(
            db=self._db,
            namespace=self.cfg.namespace,
        )

    def generate_calibration_with_sidecars(self, save_sidecars: bool = False) -> GenerateCalibrationResultWrapper:
        """
        Generate calibration and optionally save sidecars, returning unified DTO.

        This method consolidates the async execution and conditional logic
        that was previously in the interface layer.

        Args:
            save_sidecars: Whether to save JSON sidecars next to model files

        Returns:
            GenerateCalibrationResultWrapper DTO with all results
        """
        # Generate calibration (this can be heavy, caller may want to run in executor)
        calibration_result = self.generate_minmax_calibration()

        # Optionally save sidecars
        save_result = None
        saved_files = None
        total_files = None
        total_labels = None

        if save_sidecars:
            save_result = self.save_calibration_sidecars(asdict(calibration_result))
            if save_result and not isinstance(save_result, dict):
                saved_files = save_result.saved_files
                total_files = save_result.total_files
                total_labels = save_result.total_labels
            elif isinstance(save_result, dict):
                saved_files = save_result.get("saved_files")
                total_files = save_result.get("total_files")
                total_labels = save_result.get("total_labels")

        return GenerateCalibrationResultWrapper(
            status="success",
            method=calibration_result.method,
            library_size=calibration_result.library_size,
            min_samples=calibration_result.min_samples,
            calibrations=calibration_result.calibrations,
            skipped_tags=calibration_result.skipped_tags,
            saved_files=saved_files,
            total_files=total_files,
            total_labels=total_labels,
        )

    def save_calibration_sidecars(
        self, calibration_data: dict[str, Any]
    ) -> SaveCalibrationSidecarsResult | dict[str, Any]:
        """
        Save calibration data as JSON sidecar files next to model files.

        Args:
            calibration_data: Calibration data from generate_minmax_calibration()

        Returns:
            Dictionary with save results and paths
        """
        from nomarr.components.ml.ml_calibration_comp import save_calibration_sidecars

        return save_calibration_sidecars(
            calibration_data=calibration_data,
            models_dir=self.cfg.models_dir,
        )

    def get_calibration_history(
        self,
        model_name: str | None = None,
        head_name: str | None = None,
        limit: int = 100,
    ) -> list[CalibrationRunResult]:
        """
        Get calibration history with drift metrics.

        Args:
            model_name: Filter by model name (optional)
            head_name: Filter by head name (optional)
            limit: Maximum number of results

        Returns:
            List of CalibrationRunResult DTOs
        """
        model_key = f"{model_name}_{head_name}" if model_name and head_name else None
        runs = self._db.calibration_runs.list_calibration_runs(
            model_key=model_key,
            limit=limit,
        )
        return [
            CalibrationRunResult(
                id=run["id"],
                model_name=run["model_name"],
                head_name=run["head_name"],
                version=run["version"],
                file_count=run["file_count"],
                timestamp=run["timestamp"],
                p5=run["p5"],
                p95=run["p95"],
                range=run["range"],
                reference_version=run["reference_version"],
                apd_p5=run["apd_p5"],
                apd_p95=run["apd_p95"],
                srd=run["srd"],
                jsd=run["jsd"],
                median_drift=run["median_drift"],
                iqr_drift=run["iqr_drift"],
                is_stable=run["is_stable"],
            )
            for run in runs
        ]

    # -------------------------------------------------------------------------
    #  Admin Wrappers (for interfaces/api)
    # -------------------------------------------------------------------------

    def run_calibration_for_admin(self) -> RunCalibrationResult:
        """
        Generate calibration with tracking and admin-friendly error handling.

        Checks if calibrate_heads is enabled before proceeding.

        Returns:
            RunCalibrationResult with status and calibration data or error message

        Raises:
            ValueError: If calibrate_heads is disabled in config
        """
        if not self.cfg.calibrate_heads:
            raise ValueError("Calibration generation disabled. Set calibrate_heads: true in config to enable.")

        result = self.generate_calibration_with_tracking()
        return RunCalibrationResult(status="ok", calibration=asdict(result))

    def get_calibration_history_for_admin(
        self,
        model_name: str | None = None,
        head_name: str | None = None,
        limit: int = 100,
    ) -> CalibrationHistoryResult:
        """
        Get calibration history with admin-friendly error handling.

        Checks if calibrate_heads is enabled before proceeding.

        Args:
            model_name: Filter by model name (optional)
            head_name: Filter by head name (optional)
            limit: Maximum number of results

        Returns:
            CalibrationHistoryResult with runs and count

        Raises:
            ValueError: If calibrate_heads is disabled in config
        """
        if not self.cfg.calibrate_heads:
            raise ValueError("Calibration history not available. Set calibrate_heads: true in config to enable.")

        runs = self.get_calibration_history(model_name=model_name, head_name=head_name, limit=limit)
        return CalibrationHistoryResult(status="ok", runs=[asdict(r) for r in runs], count=len(runs))
