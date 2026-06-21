"""Idle vector promotion component.

Provides domain logic for idle vector promotion: enumerating hot vector
targets and computing optimal nlists parameters.  The orchestration logic
lives in ``nomarr.workflows.platform.idle_promotion_vectors_wf``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones
from nomarr.helpers.vector_params_helper import compute_nlists

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def list_hot_vector_targets(db: Database, models_dir: str) -> list[str]:
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
        stats = db.ml.get_embedding_stats(backbone_id)
        if int(stats["hot_count"]) > 0:
            targets.append(backbone_id)

    return targets


def compute_promotion_nlists(db: Database, backbone_id: str) -> int:
    """Compute optimal nlists for a backbone.

    Uses the global ``vector_group_size`` default of 15.  Sums hot and
    cold counts to determine total document count.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier.

    Returns:
        Optimal nlists value (10-4000).

    """
    # Use global group size (no per-library override)
    group_size = 15

    # Sum hot + cold counts
    stats = db.ml.get_embedding_stats(backbone_id)
    hot_count = int(stats["hot_count"])
    cold_count = int(stats["cold_count"])

    return compute_nlists(hot_count + cold_count, group_size)
