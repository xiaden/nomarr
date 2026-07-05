"""File sync component — persistence operations for single-file library sync.

Wraps persistence calls needed by library file sync via the db.library
and db.app sub-facades.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_mutation_comp import (
    update_last_tagged_at as persist_last_tagged_at,
)
from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.tagging.tag_write_comp import set_song_tags_batch
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def mark_file_processed(db: Database, file_id: str) -> None:
    """Mark a file as ML processed."""
    transition_file_state(db, [file_id], STATE_NOT_PROCESSED, STATE_PROCESSED)
    persist_last_tagged_at(db, file_id)


def save_file_tags(
    db: Database,
    file_id: str,
    parsed_tags: dict[str, list[Any]],
) -> None:
    """Write parsed tags for a file in 3 AQL round-trips instead of 3 per name."""
    entries = [{"song_id": file_id, "name": name, "values": values} for name, values in parsed_tags.items()]
    set_song_tags_batch(db, entries)
