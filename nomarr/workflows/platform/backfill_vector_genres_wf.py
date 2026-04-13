"""Workflow: backfill genres on cold vector collections.

Runs the cold-vector genre enrichment maintenance step from the workflow
layer, keeping the orchestration entrypoint out of persistence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import backfill_genres

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def backfill_vector_genres_workflow(
    db: Database,
    backbone_id: str,
    library_key: str,
) -> int:
    """Backfill missing ``genres`` arrays on a cold vector collection.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier (e.g., ``"discogs_effnet"``).
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Number of cold-vector documents updated.

    """
    logger.info(
        "[backfill vector genres wf] Starting for backbone=%s library=%s",
        backbone_id,
        library_key,
    )

    updated = backfill_genres(db, backbone_id, library_key)

    logger.info(
        "[backfill vector genres wf] Completed for backbone=%s library=%s updated=%d",
        backbone_id,
        library_key,
        updated,
    )
    return updated
