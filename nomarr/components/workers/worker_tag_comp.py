"""Tag extraction worker component.

Claim/release/discover logic for the not_hydrated state axis.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import discover_next_file_needing_tags
from nomarr.components.workers.worker_discovery_comp import claim_file, release_claim

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

__all__ = [
    "discover_and_claim_file_for_tags",
    "release_claim",
]


def discover_and_claim_file_for_tags(db: Database, worker_id: str) -> SongIdentity | None:
    """Discover and atomically claim the next file needing tag extraction.

    Args:
        db: Database instance
        worker_id: Worker identifier for claim ownership

    Returns:
        Semantic song identity if a file was claimed, ``None`` if no work is available

    """
    file_doc = discover_next_file_needing_tags(db, exclude_claimed=True)
    if file_doc is None:
        return None
    song = file_doc.identity
    if claim_file(db, song, worker_id):
        return song
    return None
