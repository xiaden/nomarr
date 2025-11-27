#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Tagger Worker
"""
tagger.py
──────────
TaggerWorker class for ML-based audio file tagging.

Extends BaseWorker to provide queue-based processing of audio files
using ML models for automatic tag generation.
"""
# ======================================================================

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.processing_dto import ProcessFileResult
from nomarr.services.config_svc import ConfigService
from nomarr.services.workers.base import BaseWorker
from nomarr.workflows.processing.process_file_wf import process_file_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.queue_svc import ProcessingQueue


class TaggerWorker(BaseWorker):
    """
    Background worker for ML-based audio file tagging.

    Polls the processing queue for pending files and tags them using
    ML models. Inherits queue polling, state management, and worker
    lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db: Database,
        queue: ProcessingQueue,
        event_broker: Any,
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize TaggerWorker.

        Args:
            db: Database instance for meta operations
            queue: ProcessingQueue instance for job operations
            event_broker: Event broker for SSE state updates (required)
            interval: Polling interval in seconds (default: 2)
            worker_id: Unique worker ID (for multi-worker setups)
        """
        # Initialize parent BaseWorker
        super().__init__(
            name="TaggerWorker",
            queue=queue,
            process_fn=self._process,
            db=db,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
        self.db = db
        self.config_service = ConfigService()

    def _process(self, path: str, force: bool) -> ProcessFileResult:
        """
        Process a single audio file with ML tagging.

        Args:
            path: Absolute path to audio file
            force: Whether to force reprocessing (ignored, uses config)

        Returns:
            ProcessFileResult DTO with processing results
        """
        config = self.config_service.make_processor_config()
        return process_file_workflow(path, config, self.db)
