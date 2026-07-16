"""Idle vector promotion: enumerate hot vector targets and compute nlists."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones
from nomarr.helpers.vector_params_helper import get_ef_construction

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


async def list_hot_vector_targets(db: Database, models_dir: str) -> list[str]:
    """Find backbone IDs with pending hot vectors.

    Enumerates backbones from the filesystem and checks each for a
    non-empty hot collection.

    Args:
        db: Database instance.
        models_dir: Root directory containing model folders.

    Returns:
        List of backbone IDs where the hot collection exists and has at
        least one document.

    """
    backbones = discover_backbones(models_dir)
    if not backbones:
        return []

    targets: list[str] = []
    for backbone_id in backbones:
        stats = await db.ml.get_embedding_stats(backbone_id)
        if int(stats["hot_count"]) > 0:
            targets.append(backbone_id)

    return targets


async def compute_promotion_ef_construction(db: Database, backbone_id: str) -> int:
    """Compute optimal HNSW ef_construction for a backbone.

    Sums hot and cold counts to determine total document count, then
    derives the build-time HNSW parameter.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier.

    Returns:
        Optimal ef_construction value (100-500).

    """
    # Sum hot + cold counts
    stats = await db.ml.get_embedding_stats(backbone_id)
    hot_count = int(stats["hot_count"])
    cold_count = int(stats["cold_count"])

    return get_ef_construction(hot_count + cold_count)
