from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.3"
DESCRIPTION: str = "Drop stale FK-based unique indexes left by V021"


def upgrade(db: DatabaseLike) -> None:
    """Drop stale unique persistent indexes from V021's FK-to-edge migration.

    V021 converted FK fields (model_id, file_id) into edges but left behind
    unique persistent indexes that were originally created to enforce FK
    uniqueness on those fields. Those indexes reference columns that no longer
    carry meaning as identity fields.

    Safe to run multiple times — operates on collection existence and index
    type/fields checks only.

    Args:
        db: ArangoDB database handle.
    """
    # Drop unique persistent index on (model_id, output_index) from ml_model_outputs
    if db.has_collection("ml_model_outputs"):
        coll = db.collection("ml_model_outputs")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "model_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V023] Dropped index {idx['fields']} from ml_model_outputs")

    # Drop unique persistent indexes referencing file_id from segment_scores_stats
    if db.has_collection("segment_scores_stats"):
        coll = db.collection("segment_scores_stats")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "file_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V023] Dropped index {idx['fields']} from segment_scores_stats")
