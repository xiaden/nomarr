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

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.processing_dto import ProcessFileResult, ProcessorConfig
from nomarr.services.infrastructure.workers.base import BaseWorker

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def create_tagger_backend(
    models_dir: Path,
    namespace: str,
    calibrate_heads: bool,
    version_tag_key: str,
) -> Callable[[Database, str, bool], ProcessFileResult | dict[str, Any]]:
    """
    Create a tagger backend function with captured config.

    This factory function creates a closure that captures application config
    and calls the process_file_workflow with appropriate settings.

    Args:
        models_dir: Path to ML models directory
        namespace: Tag namespace for written tags
        calibrate_heads: Whether to apply calibration to model outputs
        version_tag_key: Metadata key for tagger version tracking

    Returns:
        Callable backend function for TaggerWorker that accepts (db, path, force)
    """

    def tagger_backend(db: Database, path: str, force: bool):
        """Backend for TaggerWorker - runs process_file_workflow in worker process."""
        from nomarr.workflows.processing.process_file_wf import process_file_workflow

        config = ProcessorConfig(
            models_dir=str(models_dir),
            namespace=namespace,
            calibrate_heads=calibrate_heads,
            overwrite_tags=force,
            min_duration_s=10,
            allow_short=False,
            batch_size=11,
            version_tag_key=version_tag_key,
            tagger_version="1.2",
        )
        return process_file_workflow(path=path, config=config, db=None)

    return tagger_backend


class TaggerWorker(BaseWorker[ProcessFileResult | dict[str, Any]]):
    """
    Background worker for ML-based audio file tagging.

    Polls the tag_queue table for pending files and tags them using
    a provided processing backend. Inherits queue polling, state management,
    and worker lifecycle from BaseWorker.
    """

    def __init__(
        self,
        db_path: str,
        processing_backend: Callable[[Database, str, bool], ProcessFileResult | dict[str, Any]],
        event_broker: Any,
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize TaggerWorker.

        Args:
            db_path: Path to database file (worker creates its own connection)
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
            db_path=db_path,
            event_broker=event_broker,
            worker_id=worker_id,
            interval=interval,
        )
