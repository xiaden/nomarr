"""Worker discovery component.

Core discovery and claiming logic for discovery-based workers.
Workers query the songs table directly instead of polling a queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import discover_next_untagged_file
from nomarr.helpers.dataclasses.worker_claim_dataclass import (
    ClaimRemovalRequest,
    WorkerClaim,
    WorkerClaimIdentity,
)
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def discover_next_file(
    db: Database,
) -> SongStateCandidate | None:
    """Discover the next untagged song.

    Uses the song state graph to find songs in the ``not_processed`` state,
    excluding errored and already-claimed songs.

    Args:
        db: Database instance

    Returns:
        Typed state candidate or None if no work available

    """
    return discover_next_untagged_file(db, exclude_claimed=True)


def claim_file(db: Database, song: SongIdentity, worker_id: str) -> bool:
    """Attempt to claim a song addressed by its semantic locator."""
    claim = WorkerClaim(
        identity=WorkerClaimIdentity(song=song, worker_id=worker_id, claim_type=None),
        claimed_at_ms=now_ms().value,
    )
    return db.app.add_claim(claim)


def release_claim(db: Database, song: SongIdentity, worker_id: str) -> None:
    """Release an untyped claim addressed by its semantic locator."""
    db.app.remove_claim(WorkerClaimIdentity(song=song, worker_id=worker_id, claim_type=None))


def cleanup_stale_claims(db: Database, heartbeat_timeout_ms: int) -> int:
    """Remove claims from inactive workers and ineligible/errored songs.

    A thin call to the complete ``db.app.remove_claims`` cleanup intent: stale
    workers (whose heartbeat predates the cutoff), missing songs, completed
    (already tagged) songs, and errored/retry-eligible songs are all selected by
    the persistence cleanup, so ``retry_errored_songs`` is never re-blocked.
    Active pending reconcile claims are preserved by the cleanup policy.

    Args:
        db: Database instance
        heartbeat_timeout_ms: How long before a worker heartbeat is stale

    Returns:
        Number of claims removed

    """
    stale_cutoff_ms = now_ms().value - heartbeat_timeout_ms
    return db.app.remove_claims(
        ClaimRemovalRequest(
            stale_workers_before_ms=stale_cutoff_ms,
            remove_missing_songs=True,
            remove_completed_songs=True,
            remove_errored_songs=True,
        )
    )


def discover_and_claim_file(
    db: Database,
    worker_id: str,
) -> SongIdentity | None:
    """Discover and claim the next available file for processing.

    Combined operation that:
    1. Discovers next untagged song (excludes errored and claimed)
    2. Attempts to claim it
    3. Returns the semantic song identity if successful, None otherwise

    On claim conflict, returns None - caller should retry immediately.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        Semantic song identity or None if no work is available or the claim fails

    """
    candidate = discover_next_file(db)
    if candidate is None:
        logger.debug("[discovery] No files found needing processing (worker=%s)", worker_id)
        return None

    song = candidate.identity
    if claim_file(db, song, worker_id):
        logger.debug("[discovery] Claimed %s for %s", song.normalized_path, worker_id)
        return song
    # Another worker claimed this file - caller should retry
    logger.debug("[discovery] File %s already claimed, retrying discovery", song.normalized_path)
    return None


def get_active_claim_count(db: Database) -> int:
    """Get count of active claims.

    Args:
        db: Database instance

    Returns:
        Number of active claim rows

    """
    return db.app.count_claims()


def release_claims_for_worker(db: Database, worker_id: str) -> int:
    """Release all claims held by a specific worker.

    Used when a worker dies/crashes to free its claimed files for rediscovery.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        Number of claims released

    """
    return db.app.remove_claims(ClaimRemovalRequest(worker_ids=(worker_id,)))
