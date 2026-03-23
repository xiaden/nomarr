"""Retrieve a track's normalized embedding vector.

Resolves the owning library from the file, then fetches the promoted
vector from the cold collection.  Hot collections are never searched.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_library_comp import get_file_library_key
from nomarr.components.ml.vectors.ml_vector_retrieve_comp import get_cold_track_vector

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_track_vector(
    db: Database,
    file_id: str,
    backbone_id: str,
) -> dict[str, Any] | None:
    """Get a track's promoted vector by file ID and backbone.

    Pipeline:
        1. Resolve the library that owns the file
        2. Fetch the normalized vector from the cold collection

    Args:
        db: Database instance.
        file_id: Library file document ``_id`` (e.g. ``"library_files/12345"``).
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        Vector document dict (includes ``vector_n``, ``file_id``, etc.)
        or ``None`` when:
        - The file does not exist
        - The file's library cannot be resolved
        - No promoted vector exists in the cold collection

    """
    # Step 1: Resolve library from file
    library_key = get_file_library_key(db, file_id)
    if library_key is None:
        logger.debug("Cannot resolve library for file_id=%s", file_id)
        return None

    # Step 2: Get vector from cold collection
    return get_cold_track_vector(db, file_id, backbone_id, library_key)
