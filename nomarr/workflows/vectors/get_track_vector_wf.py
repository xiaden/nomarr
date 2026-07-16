"""Retrieve a track's normalized embedding vector.

Fetches the promoted vector directly from the per-backbone cold collection.
No library resolution needed — vector collections are per-backbone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import get_cold_track_vector

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


async def get_track_vector(
    db: Database,
    file_id: int,
    backbone_id: str,
) -> dict[str, Any] | None:
    """Get a track's promoted vector by file ID and backbone.

    Single step: fetches the normalized vector from the per-backbone cold
    collection. No library resolution needed.

    Args:
        db: Database instance.
        file_id: Song document ``_id`` (e.g. ``"song/12345"``).
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        Vector document dict (includes ``vector_n``, ``file_id``, etc.)
        or ``None`` when no promoted vector exists in the cold collection.

    """
    return await get_cold_track_vector(db, file_id, backbone_id)
