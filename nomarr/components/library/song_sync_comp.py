"""Song sync component — persistence operations for single-song library sync.

Wraps persistence calls needed by library song sync via the ``db.library``
and ``db.app`` sub-facades. Workflows call these functions instead of
accessing persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_mutation_comp import (
    update_last_tagged_at as persist_last_tagged_at,
)
from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.tagging.tag_write_comp import set_song_tags_batch
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Song metadata updates
# ---------------------------------------------------------------------------


def mark_song_processed(db: Database, song_id: int) -> None:
    """Mark a song as ML processed.

    Args:
        db: Database instance
        song_id: Document ``id``

    """
    transition_song_state(db, [song_id], STATE_NOT_PROCESSED, STATE_PROCESSED)
    persist_last_tagged_at(db, song_id)


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------


def save_song_tags(
    db: Database,
    song_id: int,
    parsed_tags: dict[str, list[Any]],
) -> None:
    """Write parsed tags for a song.

    Builds a batch of (song_id, name, values) entries and writes them all
    in 3 SQL round-trips instead of 3 per name.

    Args:
        db: Database instance
        song_id: Song row ID (integer)
        parsed_tags: Mapping of tag name → list of tag values

    """
    entries = [{"song_id": song_id, "name": name, "values": values} for name, values in parsed_tags.items()]
    set_song_tags_batch(db, entries)
