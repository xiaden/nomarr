#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Recalibration Worker
"""
recalibration.py
────────────────
RecalibrationWorker class for applying calibration to existing library tags.

Extends BaseWorker to provide queue-based recalibration of audio files
without re-running ML inference (uses existing numeric tags from DB).
"""
# ======================================================================

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.services.infrastructure.workers.base import BaseWorker

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class RecalibrationBackend:
    """
    Picklable recalibration backend for spawn multiprocessing.

    Stores config as instance attributes instead of closure,
    making it picklable for multiprocessing.spawn().
    """

    def __init__(
        self,
        models_dir: str,
        namespace: str,
        version_tag_key: str,
        calibrate_heads: bool,
    ):
        self.models_dir = models_dir
        self.namespace = namespace
        self.version_tag_key = version_tag_key
        self.calibrate_heads = calibrate_heads

    def __call__(self, db: Database, path: str, force: bool) -> dict[str, Any]:
        """Apply recalibration to existing file tags."""
        from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
        from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

        params = RecalibrateFileWorkflowParams(
            file_path=path,
            models_dir=self.models_dir,
            namespace=self.namespace,
            version_tag_key=self.version_tag_key,
            calibrate_heads=self.calibrate_heads,
        )
        recalibrate_file_workflow(db=db, params=params)
        return {"status": "success", "path": path}


def create_recalibration_backend(
    models_dir: Path,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool,
) -> RecalibrationBackend:
    """
    Create a recalibration backend callable with captured config.

    Returns a picklable class instance instead of a closure,
    compatible with multiprocessing.spawn().

    Args:
        models_dir: Path to ML models directory
        namespace: Tag namespace for recalibrated tags
        version_tag_key: Metadata key for tagger version tracking
        calibrate_heads: Whether to apply calibration to model outputs

    Returns:
        RecalibrationBackend instance that accepts (db, path, force)
    """
    return RecalibrationBackend(
        models_dir=str(models_dir),
        namespace=namespace,
        version_tag_key=version_tag_key,
        calibrate_heads=calibrate_heads,
    )


class RecalibrationWorker(BaseWorker):
    """
    Background worker for applying calibration to library files.

    Recalibration is much faster than retagging because it skips ML inference,
    using existing numeric tags from the database and applying new calibration
    to update mood-* tags.

    Polls calibration_queue table for pending recalibration jobs.

    Inherits queue polling, state management, and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db_path: str,
        processing_backend: Callable[[Database, str, bool], dict[str, Any]],
        event_broker: Any,
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize RecalibrationWorker.

        Args:
            db_path: Path to database file (worker creates its own connection)
            processing_backend: Backend function for processing files
            event_broker: Event broker for SSE state updates (required)
            interval: Polling interval in seconds (default: 2)
            worker_id: Unique worker ID (for multi-worker setups)
        """
        # Initialize parent BaseWorker with calibration queue type
        super().__init__(
            name="RecalibrationWorker",
            queue_type="calibration",
            process_fn=processing_backend,
            db_path=db_path,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
