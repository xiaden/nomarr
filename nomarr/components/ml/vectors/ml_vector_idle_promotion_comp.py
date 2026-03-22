"""Idle vector promotion component.

Provides domain logic for idle vector promotion: enumerating hot vector
targets and computing optimal nlists parameters.  The orchestration logic
lives in ``nomarr.workflows.platform.idle_promotion_vectors_wf``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def list_hot_vector_targets(
    db: Database, models_dir: str
) -> list[tuple[str, str]]:
    """Find all (backbone_id, library_key) pairs with pending hot vectors.

    Enumerates backbones from the filesystem and libraries from the database,
    then checks each combination for a non-empty hot collection.

    Args:
        db: Database instance.
        models_dir: Root directory containing model folders.

    Returns:
        List of ``(backbone_id, library_key)`` tuples where the hot
        collection exists and has at least one document.

    """
    from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones

    backbones = discover_backbones(models_dir)
    if not backbones:
        return []

    libraries = db.libraries.list_libraries()
    if not libraries:
        return []

    targets: list[tuple[str, str]] = []
    for backbone_id in backbones:
        for lib_doc in libraries:
            library_key: str = lib_doc["_key"]
            hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
            if not db.db.has_collection(hot_coll_name):  # type: ignore[union-attr]
                continue
            hot_ops = db.register_vectors_track_backbone(backbone_id, library_key)
            if hot_ops.count() > 0:
                targets.append((backbone_id, library_key))

    return targets


def compute_promotion_nlists(db: Database, backbone_id: str, library_key: str) -> int:
    """Compute optimal nlists for a backbone+library pair.

    Reads per-library ``vector_group_size`` from the library document,
    falling back to the default of 15.  Sums hot and cold counts to
    determine total document count.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.

    Returns:
        Optimal nlists value (10-4000).

    """
    from nomarr.helpers.vector_params_helper import compute_nlists

    # Read per-library group size (fallback to default 15)
    group_size = 15
    lib_doc = db.libraries.get_library(library_key)
    if lib_doc is not None:
        lib_group_size = lib_doc.get("vector_group_size")
        if lib_group_size is not None:
            group_size = int(lib_group_size)

    # Sum hot + cold counts
    hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"

    hot_count = 0
    if db.db.has_collection(hot_coll_name):  # type: ignore[union-attr]
        hot_count = db.register_vectors_track_backbone(backbone_id, library_key).count()

    cold_count = 0
    if db.db.has_collection(cold_coll_name):  # type: ignore[union-attr]
        cold_count = db.get_vectors_track_cold(backbone_id, library_key).count()

    return compute_nlists(hot_count + cold_count, group_size)


