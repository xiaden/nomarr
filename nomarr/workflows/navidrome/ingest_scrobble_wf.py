"""Ingest a single scrobble event into the play-count graph.

Receives a Navidrome scrobble (user + track + timestamp), deduplicates
within a 30-second window, and atomically increments the play count.
File resolution is attempted for observability but never blocks.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from nomarr.components.navidrome.navidrome_graph_comp import (
    increment_navidrome_play,
    resolve_navidrome_track_to_file,
    upsert_navidrome_track,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_MS = 30_000

_dedup_lock = threading.Lock()
_dedup_cache: dict[tuple[str, str], int] = {}


def ingest_scrobble(db: Database, user_id: str, nd_id: str, timestamp_ms: int) -> None:
    """Ingest a real-time scrobble event.

    Sequence:
        1. Dedup check — skip if same (user, track) within 30 s.
        2. Upsert track vertex.
        3. Atomically increment play count (creates bucket vertex if needed).
        4. Attempt file resolution (log-only, never blocks).

    Args:
        db: Database instance.
        user_id: Navidrome user identifier.
        nd_id: Navidrome track (song) identifier.
        timestamp_ms: Epoch milliseconds of the scrobble event.

    """
    # Step 1: Dedup check
    cache_key = (user_id, nd_id)
    with _dedup_lock:
        last_ts = _dedup_cache.get(cache_key)
        if last_ts is not None and (timestamp_ms - last_ts) < _DEDUP_WINDOW_MS:
            logger.debug(
                "Duplicate scrobble suppressed: user=%s track=%s delta=%dms",
                user_id,
                nd_id,
                timestamp_ms - last_ts,
            )
            return
        _dedup_cache[cache_key] = timestamp_ms

    # Step 2: Upsert track vertex
    upsert_navidrome_track(db, nd_id)

    # Step 3: Atomically increment play count (creates bucket if needed)
    increment_navidrome_play(db, user_id, nd_id, timestamp_ms)

    # Step 4: Attempt file resolution (observability only)
    file_id = resolve_navidrome_track_to_file(db, nd_id)
    if file_id:
        logger.debug("Scrobble resolved: nd_id=%s -> %s", nd_id, file_id)
    else:
        logger.debug("Scrobble unresolved: nd_id=%s (no has_nd_id edge yet)", nd_id)
