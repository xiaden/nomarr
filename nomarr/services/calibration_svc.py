"""
CalibrationService - Thin orchestration wrapper for calibration generation workflow.

This service delegates to workflows.calibration_generation for the actual calibration logic.
It provides dependency injection (db, models_dir, namespace, thresholds) from the application
context to the pure workflow function.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.calibration_dto import CalibrationRunResult, GenerateCalibrationResult
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
        runs = self._db.calibration_runs.list_calibration_runs(
            model_name=model_name,
            head_name=head_name,
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
