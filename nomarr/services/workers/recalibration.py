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

from typing import TYPE_CHECKING, Any

from nomarr.services.workers.base import BaseWorker
from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.queue_svc import RecalibrationQueue


class RecalibrationWorker(BaseWorker):
    """
    Background worker for applying calibration to library files.

    Recalibration is much faster than retagging because it skips ML inference,
    using existing numeric tags from the database and applying new calibration
    to update mood-* tags.

    Inherits queue polling, state management, and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db: Database,
        queue: RecalibrationQueue,
        event_broker: Any,
        models_dir: str,
        namespace: str = "nom",
        version_tag_key: str = "nom_version",
        interval: int = 2,
        worker_id: int = 0,
        calibrate_heads: bool = False,
    ):
        """
        Initialize RecalibrationWorker.

        Args:
            db: Database instance for meta operations
            queue: RecalibrationQueue instance for job operations
            event_broker: Event broker for SSE state updates (required)
            models_dir: Path to models directory (for loading calibration sidecars)
            namespace: Tag namespace (default: "nom")
            version_tag_key: Tag key used for version identification (default: "nom_version")
            interval: Polling interval in seconds (default: 2)
            worker_id: Unique worker ID (for multi-worker setups)
            calibrate_heads: If True, use versioned calibration files (dev mode)
        """
        # Initialize parent BaseWorker
        super().__init__(
            name="RecalibrationWorker",
            queue=queue,
            process_fn=self._process,
            db=db,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
        self.db = db
        self.models_dir = models_dir
        self.namespace = namespace
        self.version_tag_key = version_tag_key
        self.calibrate_heads = calibrate_heads

    def _process(self, path: str, force: bool) -> dict[str, Any]:
        """
        Recalibrate a single audio file.

        Args:
            path: Absolute path to audio file
            force: Whether to force reprocessing (ignored for recalibration)

        Returns:
            Dict with processing results
        """
        recalibrate_file_workflow(
            db=self.db,
            file_path=path,
            models_dir=self.models_dir,
            namespace=self.namespace,
            version_tag_key=self.version_tag_key,
            calibrate_heads=self.calibrate_heads,
        )
        return {"status": "success", "path": path}
