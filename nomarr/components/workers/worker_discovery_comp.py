"""Worker discovery component.

Core discovery and claiming logic for discovery-based workers.
Workers query the songs table directly instead of polling a queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_song_state_comp import discover_next_untagged_file
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)
_TAGGED_STATE_ID = "tagged"


def _claim_key(file_id: str | int) -> str:
    """Build the deterministic worker-claim key for a file."""
    return f"claim_{file_id}"


def _get_all_claims(db: Database) -> list[dict[str, Any]]:
    """Return all worker claims via the application facade."""
    return cast("list[dict[str, Any]]", db.app.list_claims())


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
    """Attempt to claim file for processing.

    Uses deterministic key based on file id to enforce uniqueness.
    PostgreSQL unique constraint prevents duplicate claims.

    Args:
        db: Database instance
        file_id: Song id (e.g., ``12345``)
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        True if claim successful, False if already claimed

    """
    try:
        db.app.claim_song(int(file_id), worker_id, claimed_at=now_ms().value)
    except DuplicateEntityError:
        return False
    return True


def release_claim(db: Database, file_id: int, worker_id: str) -> None:
    """Release claim on file (after processing or error).

    Args:
        db: Database instance
        file_id: Song id

    """
    db.app.remove_claim(worker_id, file_id, "process")


def try_insert_or_steal_claim(
    db: Database,
    payload: dict[str, Any],
    now: int,
    lease_ms: int,
) -> bool:
    """Try to insert a claim, stealing it if the existing one is expired.

    Args:
        db: Database handle.
        payload: Claim metadata including ``file_id``, ``worker_id``, and
            ``claimed_at``.
        now: Current timestamp in milliseconds.
        lease_ms: Claim lease duration in ms; existing claims older than this
            threshold are considered expired and may be stolen.

    Returns:
        True if the claim was successfully inserted (new or stolen);
        False if an active un-expired claim already exists.

    """
    file_id = int(payload["file_id"])
    worker_id = str(payload["worker_id"])
    claim_type = payload.get("claim_type")
    claimed_at = int(payload.get("claimed_at", 0))
    try:
        db.app.claim_song(file_id, worker_id, claim_type=claim_type, claimed_at=claimed_at)
    except DuplicateEntityError:
        file_id = int(payload["file_id"])
        all_claims = _get_all_claims(db)
        existing_claim = next(
            (claim for claim in all_claims if str(claim.get("file_id")) == str(file_id)),
            None,
        )
        if existing_claim is None:
            try:
                db.app.claim_song(file_id, worker_id, claim_type=claim_type, claimed_at=claimed_at)
            except DuplicateEntityError:
                return False
            return True

        claimed_at = int(existing_claim.get("claimed_at", 0))
        if claimed_at > now - lease_ms:
            return False

        db.app.remove_claim_by_song(int(file_id), str(claim_type or "process"))
        try:
            db.app.claim_song(file_id, worker_id, claim_type=claim_type, claimed_at=claimed_at)
        except DuplicateEntityError:
            return False
        return True
    return True


def cleanup_stale_claims(db: Database, heartbeat_timeout_ms: int) -> int:
    """Remove claims from inactive workers and completed/ineligible files.

    Cleanup runs all three cleanup operations:
    1. Claims from workers with stale heartbeats
    2. Claims for files that are already tagged
    3. Claims for files that no longer need processing

    Args:
        db: Database instance
        heartbeat_timeout_ms: How long before a worker heartbeat is stale

    Returns:
        Number of claims removed

    """
    all_claims = _get_all_claims(db)
    if not all_claims:
        return 0

    heartbeat_cutoff = now_ms().value - heartbeat_timeout_ms
    health_docs = cast("list[dict[str, Any]]", db.app.list_worker_health())
    active_workers = {
        str(doc.get("worker_id")) for doc in health_docs if int(doc.get("last_seen", 0)) > heartbeat_cutoff
    }

    inactive_worker_ids = {
        str(claim["worker_id"]) for claim in all_claims if str(claim["worker_id"]) not in active_workers
    }
    active_ml_claims = [
        claim
        for claim in all_claims
        if str(claim["worker_id"]) in active_workers and claim.get("claim_type") != "reconcile"
    ]

    stale_song_ids: set[int] = set()
    candidate_song_ids = sorted({int(claim["file_id"]) for claim in active_ml_claims})
    if candidate_song_ids:
        song_docs = cast("list[dict[str, Any]]", db.library.list_songs_by_ids(candidate_song_ids))
        existing_song_ids = {doc["id"] for doc in song_docs if "id" in doc}

        tagged_song_ids = {
            song_doc["id"]
            for song_doc in cast("list[dict[str, Any]]", db.app.list_song_docs_in_state(_TAGGED_STATE_ID))
            if "id" in song_doc and song_doc["id"] in candidate_song_ids
        }
        stale_song_ids = {
            song_id for song_id in candidate_song_ids if song_id not in existing_song_ids or song_id in tagged_song_ids
        }

    removed = 0
    if inactive_worker_ids:
        removed += db.app.remove_claims(worker_ids=sorted(inactive_worker_ids))
    if stale_song_ids:
        removed += db.app.remove_claims(song_ids=sorted(stale_song_ids))
    return removed


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
        Number of active claim documents

    """
    return len(db.app.list_claims())


def release_claims_for_worker(db: Database, worker_id: str) -> list[str]:
    """Release all claims held by a specific worker.

    Used when a worker dies/crashes to free its claimed files for rediscovery.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        List of file_ids that were released

    """
    claims = [
        claim
        for claim in cast("list[dict[str, Any]]", db.app.list_claims())
        if str(claim.get("worker_id")) == worker_id
    ]
    if not claims:
        return []

    file_ids = [str(claim["file_id"]) for claim in claims]
    db.app.remove_claims(worker_ids=[worker_id])
    return file_ids
