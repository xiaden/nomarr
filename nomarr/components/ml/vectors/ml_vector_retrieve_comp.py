"""Retrieve a track's normalized embedding from the cold vector collection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_cold_track_vector(
    db: Database,
    file_id: str,
    backbone_id: str,
    library_key: str,
) -> dict[str, Any] | None:
    """Fetch a track's vector document from the cold collection.

    Cold collections hold promoted, indexed vectors.  Hot collections are
    write-only (accumulation during ML processing) and must never be
    searched.

    Args:
        db: Database instance.
        file_id: Library file document ``_id``.
        backbone_id: Backbone identifier (e.g. ``"effnet"``).
        library_key: ArangoDB ``_key`` of the owning library.

    Returns:
        Vector document dict (includes ``vector_n``, ``score``, etc.)
        or ``None`` if no promoted vector exists.

    """
    cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"

    if not db.db.has_collection(cold_coll_name):
        logger.debug(
            "Cold collection %s does not exist for backbone=%s, library=%s",
            cold_coll_name,
            backbone_id,
            library_key,
        )
        return None

    cold_ops = db.get_vectors_track_cold(backbone_id, library_key)
    return cold_ops.get_vector(file_id)
