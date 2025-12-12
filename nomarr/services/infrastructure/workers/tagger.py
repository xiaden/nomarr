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


class TaggerBackend:
    """
    Picklable tagger backend for spawn multiprocessing.

    Stores config as instance attributes instead of closure,
    making it picklable for multiprocessing.spawn().
    """

    def __init__(
        self,
        models_dir: str,
        namespace: str,
        calibrate_heads: bool,
        version_tag_key: str,
        tagger_version: str,
    ):
        self.models_dir = models_dir
        self.namespace = namespace
        self.calibrate_heads = calibrate_heads
        self.version_tag_key = version_tag_key
        self.tagger_version = tagger_version

    def __call__(self, db: Database, path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
        """Process file with ML tagging workflow."""
        from nomarr.workflows.processing.process_file_wf import process_file_workflow

        config = ProcessorConfig(
            models_dir=self.models_dir,
            namespace=self.namespace,
            calibrate_heads=self.calibrate_heads,
            overwrite_tags=force,
            min_duration_s=10,
            allow_short=False,
            batch_size=11,
            version_tag_key=self.version_tag_key,
            tagger_version=self.tagger_version,
        )
        return process_file_workflow(path=path, config=config, db=db)


def create_tagger_backend(
    models_dir: Path,
    namespace: str,
    calibrate_heads: bool,
    version_tag_key: str,
    tagger_version: str,
) -> TaggerBackend:
    """
    Create a tagger backend callable with captured config.

    Returns a picklable class instance instead of a closure,
    compatible with multiprocessing.spawn().

    Args:
        models_dir: Path to ML models directory
        namespace: Tag namespace for written tags
        calibrate_heads: Whether to apply calibration to model outputs
        version_tag_key: Metadata key for tagger version tracking
        tagger_version: Current Nomarr version for tag versioning

    Returns:
        TaggerBackend instance that accepts (db, path, force)
    """
    return TaggerBackend(
        models_dir=str(models_dir),
        namespace=namespace,
        calibrate_heads=calibrate_heads,
        version_tag_key=version_tag_key,
        tagger_version=tagger_version,
    )


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
        interval: int = 2,
        worker_id: int = 0,
    ):
        """
        Initialize TaggerWorker.

        Args:
            db_path: Path to database file (worker creates its own connection)
            processing_backend: Backend function for processing files
            interval: Polling interval in seconds (default: 2)
            worker_id: Unique worker ID (for multi-worker setups)
        """
        # Initialize parent BaseWorker with tag queue type
        super().__init__(
            name="TaggerWorker",
            queue_type="tag",
            process_fn=processing_backend,
            db_path=db_path,
            worker_id=worker_id,
            interval=interval,
        )

        # TaggerWorker has expensive TF cache that loads on first job
        self._cache_loaded = False
