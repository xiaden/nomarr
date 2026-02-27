"""V012: Drop gpu_warmup_claims collection.

Background
----------
The ``gpu_warmup_claims`` collection was introduced to serialise GPU cache
warming across discovery workers — only one worker could hold the exclusive
claim and load models into VRAM; others skipped to CPU-only processing.

This mechanism was made fully redundant when the per-model VRAM coordinator
(``vram_promises`` collection, ``ml_vram_coordinator_comp``) was added.
Every ``BaseONNXModel.load()`` already performs an atomic AQL fit-check per
model, so concurrent GPU cache warming is safe: models that don't fit in
the remaining headroom are placed on CPU automatically.

Beyond being redundant, the GPU claim caused a file-claim leak: when a worker
lost the contention it did ``continue`` in the main loop after already having
claimed a library file, orphaning that file's claim until TTL expiry.

This migration drops the collection. All claim-gating code has been removed
from the application. Forward-only; no downgrade path.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 11
SCHEMA_VERSION_AFTER: int = 12
DESCRIPTION: str = "Drop gpu_warmup_claims collection (superseded by vram_promises coordinator)"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Drop the gpu_warmup_claims collection if it exists.

    Idempotent — safe to run multiple times.

    Args:
        db: ArangoDB database handle.

    """
    from arango.exceptions import CollectionDeleteError

    if db.has_collection("gpu_warmup_claims"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionDeleteError):
            db.delete_collection("gpu_warmup_claims")  # type: ignore[union-attr]
        logger.info("Migration V012: Dropped gpu_warmup_claims collection")
    else:
        logger.info("Migration V012: gpu_warmup_claims collection not found — nothing to do")

    logger.info("Migration V012: Complete")
