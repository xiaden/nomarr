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

from nomarr.persistence.db import Database
from nomarr.services.config import ConfigService
from nomarr.services.queue import ProcessingQueue
from nomarr.services.workers.base import BaseWorker
from nomarr.workflows.process_file import process_file_workflow


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

    # Adapter to match BaseWorker's expected signature: (path: str, force: bool) -> dict
    def _process_adapter(path: str, force: bool) -> dict[str, Any]:
        """Adapt process_file signature to match BaseWorker expectations."""
        config_service = ConfigService()
        config = config_service.make_processor_config()
        # Note: force parameter is ignored - config comes from DB/YAML
        return process_file_workflow(path, config, db)

    return BaseWorker(
        name="TaggerWorker",
        queue=queue,
        process_fn=_process_adapter,
        db=db,
        event_broker=event_broker,
        worker_id=worker_id,
        interval=interval,
    )
