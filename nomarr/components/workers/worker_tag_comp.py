"""Tag extraction worker component.

Claim/release/discover logic for the tags_not_extracted state axis.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.library_file_state_comp import discover_next_file_needing_tags
from nomarr.components.workers.worker_discovery_comp import claim_file, release_claim

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

__all__ = [
    "discover_and_claim_file_for_tags",
    "release_claim",
]


def discover_and_claim_file_for_tags(db: Database, worker_id: str) -> str | None:
    """Discover and atomically claim the next file needing tag extraction.

    Args:
        db: Database instance
        worker_id: Worker identifier for claim ownership

    Returns:
        File ``_id`` string if a file was claimed, ``None`` if no work available

    """
    file_doc = discover_next_file_needing_tags(db, exclude_claimed=True)
    if file_doc is None:
        return None
    file_id = str(file_doc["_id"])
    if claim_file(db, file_id, worker_id):
        return file_id
    return None
