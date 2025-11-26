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

from nomarr.workflows.calibration.generate_calibration_wf import generate_calibration_workflow

if TYPE_CHECKING:
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

    def generate_calibration_with_tracking(self) -> dict[str, Any]:
        """
        Generate calibrations for all heads and track drift metrics.

        Delegates to workflows.calibration_generation.generate_calibration_workflow.

        Returns:
            Dict with:
                - version: New calibration version number
                - library_size: Number of files analyzed
                - heads: Dict of head results with drift metrics
                - saved_files: Paths to saved calibration files
                - summary: Overall statistics
        """
        logger.debug("[CalibrationService] Delegating to calibration generation workflow")

        return generate_calibration_workflow(
            db=self._db,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            thresholds=self.cfg.thresholds,
        )

    def generate_minmax_calibration(self) -> dict[str, Any]:
        """
        Generate minmax calibration data from database tags.

        Returns:
            Calibration data dictionary with min/max values per head
        """
        from nomarr.components.ml.ml_calibration_comp import generate_minmax_calibration

        return generate_minmax_calibration(
            db=self._db,
            namespace=self.cfg.namespace,
        )

    def save_calibration_sidecars(self, calibration_data: dict[str, Any]) -> dict[str, Any]:
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
    ) -> list[dict[str, Any]]:
        """
        Get calibration history with drift metrics.

        Args:
            model_name: Filter by model name (optional)
            head_name: Filter by head name (optional)
            limit: Maximum number of results

        Returns:
            List of calibration run dictionaries
        """
        return self._db.calibration_runs.list_calibration_runs(
            model_name=model_name,
            head_name=head_name,
            limit=limit,
        )
