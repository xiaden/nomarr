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
from nomarr.services.workers.base import BaseWorker

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.processing_backends import ProcessingBackend


class TaggerWorker(BaseWorker[ProcessFileResult | dict[str, Any]]):
    """
    Background worker for ML-based audio file tagging.

    Polls the tag_queue table for pending files and tags them using
    a provided processing backend. Inherits queue polling, state management,
    and worker lifecycle from BaseWorker.
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
        Initialize TaggerWorker.

        Args:
            db: Database instance for queue and meta operations
            processing_backend: Backend function for processing files
            event_broker: Event broker for SSE state updates (required)
            interval: Polling interval in seconds (default: 2)
            worker_id: Unique worker ID (for multi-worker setups)
        """
        # Initialize parent BaseWorker with tag queue type
        super().__init__(
            name="TaggerWorker",
            queue_type="tag",
            process_fn=processing_backend,
            db=db,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
        self.db = db
