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
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def discover_next_file(
    db: Database,
) -> str | None:
    """Discover the next untagged song.

    Uses the song state graph to find songs in the ``not_processed`` state,
    excluding errored and already-claimed songs.

    Args:
        db: Database instance

    Returns:
        Song id or None if no work available

    """
    file_doc = discover_next_untagged_file(db, exclude_claimed=True)
    if file_doc:
        return str(file_doc["id"])
    return None


def claim_file(db: Database, file_id: str, worker_id: str) -> bool:
    """Attempt to claim a song for processing.

    Resolves the numeric song handle to its natural domain identity through the
    sanctioned ``db.library`` identity bridge and acquires an untyped worker
    claim via the ``db.app.add_claim`` intent.  The caller never constructs or
    parses a claim key, reads a raw payload, or queries state tables.

    Args:
        db: Database instance
        file_id: Song id (e.g., ``12345``)
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        True if the claim was acquired; False if the song cannot be resolved
        or an active claim already exists.

    """
    identity = db.library.resolve_song_identity(int(file_id))
    if identity is None:
        return False
    claim = WorkerClaim(
        identity=WorkerClaimIdentity(song=identity, worker_id=worker_id, claim_type=None),
        claimed_at_ms=now_ms().value,
    )
    return db.app.add_claim(claim)


def release_claim(db: Database, file_id: int, worker_id: str) -> None:
    """Release an untyped claim on a song (after processing or error).

    The claim identity is resolved through the sanctioned library bridge; a
    song that can no longer be resolved has no claim to release.

    Args:
        db: Database instance
        file_id: Song id

    """
    identity = db.library.resolve_song_identity(int(file_id))
    if identity is None:
        return
    db.app.remove_claim(WorkerClaimIdentity(song=identity, worker_id=worker_id, claim_type=None))


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
) -> str | None:
    """Discover and claim the next available file for processing.

    Combined operation that:
    1. Discovers next untagged song (excludes errored and claimed)
    2. Attempts to claim it
    3. Returns file_id if successful, None otherwise

    On claim conflict, returns None - caller should retry immediately.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        Claimed file id or None if no work available or claim failed

    """
    file_id = discover_next_file(db)
    if not file_id:
        logger.debug("[discovery] No files found needing processing (worker=%s)", worker_id)
        return None

    if claim_file(db, file_id, worker_id):
        logger.debug("[discovery] Claimed %s for %s", file_id, worker_id)
        return file_id
    # Another worker claimed this file - caller should retry
    logger.debug("[discovery] File %s already claimed, retrying discovery", file_id)
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
