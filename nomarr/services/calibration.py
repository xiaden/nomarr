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
        namespace: str = "nom",
        thresholds: dict[str, float] | None = None,
    ):
        """
        Initialize calibration service.

        Args:
            db: Database instance
            models_dir: Path to models directory
            namespace: Tag namespace (default "nom")
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
