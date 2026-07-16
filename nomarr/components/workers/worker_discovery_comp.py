"""Worker discovery component.

Core discovery and claiming logic for discovery-based workers.
Workers query the songs collection directly instead of polling a queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_state_comp import discover_next_untagged_file
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.exceptions import DuplicateKeyError

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)
_TAGGED_STATE_ID = "tagged"


def _claim_key(file_id: str | int) -> str:
    """Build the deterministic worker-claim key for a file."""
    return f"claim_{file_id}"


async def _get_all_claims(db: Database) -> list[dict[str, Any]]:
    """Return all worker claims via the application facade."""
    return cast("list[dict[str, Any]]", await db.app.list_claims())


async def discover_next_file(
    db: Database,
) -> str | None:
    """Discover next untagged file.

    Uses file_states graph traversal to find files in the not_tagged state,
    excluding too_short and already-claimed files.

    Args:
        db: Database instance

    Returns:
        File id or None if no work available

    """
    file_doc = await discover_next_untagged_file(db, exclude_claimed=True)
    if file_doc:
        return str(file_doc["id"])
    return None


async def claim_file(db: Database, file_id: str, worker_id: str) -> bool:
    """Attempt to claim file for processing.

    Uses deterministic key based on file id to enforce uniqueness.
    PostgreSQL unique constraint prevents duplicate claims.

    Args:
        db: Database instance
        file_id: File document id (e.g., ``12345``)
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        True if claim successful, False if already claimed

    """
    payload = {
        "key": _claim_key(file_id),
        "file_id": file_id,
        "worker_id": worker_id,
        "claimed_at": now_ms().value,
    }
    try:
        await db.app.add_claim(payload)
    except DuplicateKeyError:
        return False
    return True


async def release_claim(db: Database, file_id: int) -> None:
    """Release claim on file (after processing or error).

    Args:
        db: Database instance
        file_id: File document id

    """
    await db.app.remove_claim(file_id)


async def try_insert_or_steal_claim(
    db: Database,
    payload: dict[str, Any],
    now: int,
    lease_ms: int,
) -> bool:
    """Try to insert a claim, stealing it if the existing one is expired.

    Args:
        db: Database handle.
        payload: Full claim document payload including ``key``, ``file_id``,
            ``worker_id``, and ``claimed_at``.
        now: Current timestamp in milliseconds.
        lease_ms: Claim lease duration in ms; existing claims older than this
            threshold are considered expired and may be stolen.

    Returns:
        True if the claim was successfully inserted (new or stolen);
        False if an active un-expired claim already exists.

    """
    try:
        await db.app.add_claim(payload)
    except DuplicateKeyError:
        file_id = int(payload["file_id"])
        all_claims = await _get_all_claims(db)
        existing_claim = next(
            (claim for claim in all_claims if str(claim.get("file_id")) == str(file_id)),
            None,
        )
        if existing_claim is None:
            try:
                await db.app.add_claim(payload)
            except DuplicateKeyError:
                return False
            return True

        claimed_at = int(existing_claim.get("claimed_at", 0))
        if claimed_at > now - lease_ms:
            return False

        await db.app.remove_claim(file_id)
        try:
            await db.app.add_claim(payload)
        except DuplicateKeyError:
            return False
        return True
    return True


async def cleanup_stale_claims(db: Database, heartbeat_timeout_ms: int) -> int:
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
    all_claims = await _get_all_claims(db)
    if not all_claims:
        return 0

    heartbeat_cutoff = now_ms().value - heartbeat_timeout_ms
    health_docs = cast("list[dict[str, Any]]", await db.app.list_worker_health())
    active_workers = {
        str(doc.get("component_id")) for doc in health_docs if int(doc.get("last_heartbeat", 0)) > heartbeat_cutoff
    }

    inactive_worker_ids = {
        str(claim["worker_id"]) for claim in all_claims if str(claim["worker_id"]) not in active_workers
    }
    active_ml_claims = [
        claim
        for claim in all_claims
        if str(claim["worker_id"]) in active_workers and claim.get("claim_type") != "reconcile"
    ]

    stale_file_ids: set[int] = set()
    candidate_file_ids = sorted({int(claim["file_id"]) for claim in active_ml_claims})
    if candidate_file_ids:
        file_docs = cast("list[dict[str, Any]]", await db.library.list_files_by_ids(candidate_file_ids))
        existing_file_ids = {doc["id"] for doc in file_docs if "id" in doc}

        tagged_file_ids = {
            file_doc["id"]
            for file_doc in cast("list[dict[str, Any]]", await db.app.list_file_docs_in_state(_TAGGED_STATE_ID))
            if "id" in file_doc and file_doc["id"] in candidate_file_ids
        }
        stale_file_ids = {
            file_id for file_id in candidate_file_ids if file_id not in existing_file_ids or file_id in tagged_file_ids
        }

    removed = 0
    if inactive_worker_ids:
        removed += await db.app.remove_claims(worker_ids=sorted(inactive_worker_ids))
    if stale_file_ids:
        removed += await db.app.remove_claims(file_ids=sorted(stale_file_ids))
    return removed


async def discover_and_claim_file(
    db: Database,
    worker_id: str,
) -> str | None:
    """Discover and claim the next available file for processing.

    Combined operation that:
    1. Discovers next untagged file (excludes too_short and claimed)
    2. Attempts to claim it
    3. Returns file_id if successful, None otherwise

    On claim conflict, returns None - caller should retry immediately.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        Claimed file id or None if no work available or claim failed

    """
    file_id = await discover_next_file(db)
    if not file_id:
        logger.debug("[discovery] No files found needing processing (worker=%s)", worker_id)
        return None

    if await claim_file(db, file_id, worker_id):
        logger.debug("[discovery] Claimed %s for %s", file_id, worker_id)
        return file_id
    # Another worker claimed this file - caller should retry
    logger.debug("[discovery] File %s already claimed, retrying discovery", file_id)
    return None


async def get_active_claim_count(db: Database) -> int:
    """Get count of active claims.

    Args:
        db: Database instance

    Returns:
        Number of active claim documents

    """
    return len(await db.app.list_claims())


async def release_claims_for_worker(db: Database, worker_id: str) -> list[str]:
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
        for claim in cast("list[dict[str, Any]]", await db.app.list_claims())
        if str(claim.get("worker_id")) == worker_id
    ]
    if not claims:
        return []

    file_ids = [str(claim["file_id"]) for claim in claims]
    await db.app.remove_claims(worker_ids=[worker_id])
    return file_ids
