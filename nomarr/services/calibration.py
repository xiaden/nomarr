"""
CalibrationService - Thin orchestration wrapper for calibration generation workflow.

This service delegates to workflows.calibration_generation for the actual calibration logic.
It provides dependency injection (db, models_dir, namespace, thresholds) from the application
context to the pure workflow function.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.workflows.generate_calibration import generate_calibration_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


class CalibrationService:
    """
    Service for orchestrating calibration generation.

    Thin wrapper that provides DI to the calibration workflow.
    All domain logic lives in workflows.calibration_generation.
    """

    def __init__(
        self,
        db: Database,
        models_dir: str,
        namespace: str,
        thresholds: dict[str, float] | None = None,
    ):
        """
        Initialize calibration service.

        Args:
            db: Database instance
            models_dir: Path to models directory
            namespace: Tag namespace (must be provided by service)
            thresholds: Optional custom drift thresholds
        """
        self._db = db
        self._models_dir = models_dir
        self._namespace = namespace
        self._thresholds = thresholds or {}

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
            models_dir=self._models_dir,
            namespace=self._namespace,
            thresholds=self._thresholds,
        )

    def generate_minmax_calibration(self) -> dict[str, Any]:
        """
        Generate minmax calibration data from database tags.

        Returns:
            Calibration data dictionary with min/max values per head
        """
        from nomarr.ml.calibration import generate_minmax_calibration

        return generate_minmax_calibration(
            db=self._db,
            namespace=self._namespace,
        )

    def save_calibration_sidecars(self, calibration_data: dict[str, Any]) -> dict[str, Any]:
        """
        Save calibration data as JSON sidecar files next to model files.

        Args:
            calibration_data: Calibration data from generate_minmax_calibration()

        Returns:
            Dictionary with save results and paths
        """
        from nomarr.ml.calibration import save_calibration_sidecars

        return save_calibration_sidecars(
            calibration_data=calibration_data,
            models_dir=self._models_dir,
        )
