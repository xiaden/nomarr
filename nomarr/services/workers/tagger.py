#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Tagger Worker Factory
"""
tagger.py
──────────
Factory function for creating TaggerWorker instances.

Creates a BaseWorker configured for audio file tagging using ML models.
"""
# ======================================================================

from __future__ import annotations

from typing import Any

from nomarr.core.processor import process_file
from nomarr.data.db import Database
from nomarr.data.queue import ProcessingQueue
from nomarr.services.workers.base import BaseWorker


def create_tagger_worker(
    db: Database,
    queue: ProcessingQueue,
    event_broker: Any,
    interval: int = 2,
    worker_id: int = 0,
) -> BaseWorker:
    """
    Create a TaggerWorker for ML-based audio file tagging.

    Args:
        db: Database instance for meta operations
        queue: ProcessingQueue instance for job operations
        event_broker: Event broker for SSE state updates (required)
        interval: Polling interval in seconds (default: 2)
        worker_id: Unique worker ID (for multi-worker setups)

    Returns:
        BaseWorker instance configured for tagging operations
    """
    return BaseWorker(
        name="TaggerWorker",
        queue=queue,
        process_fn=process_file,  # Inject ML processing logic
        db=db,
        event_broker=event_broker,
        worker_id=worker_id,
        interval=interval,
    )
