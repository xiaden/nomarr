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

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.processing_backends import ProcessingBackend


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
        db: Database,
        processing_backend: ProcessingBackend,
        event_broker: Any,
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize RecalibrationWorker.

        Args:
            db: Database instance for queue and meta operations
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
            db=db,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
        self.db = db
