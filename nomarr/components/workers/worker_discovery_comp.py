"""Worker discovery component.

Core discovery and claiming logic for discovery-based workers.
Workers query library_files directly instead of polling a queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from arango.exceptions import DocumentInsertError

from nomarr.components.library.library_file_query_comp import get_file_by_id
from nomarr.components.library.library_file_state_comp import discover_next_untagged_file, file_has_tagged_state
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _claim_key(file_id: str) -> str:
    """Build the deterministic worker-claim key for a file."""
    file_key = file_id.split("/")[1] if "/" in file_id else file_id
    return f"claim_{file_key}"


def _get_all_claims(db: Database) -> list[dict[str, Any]]:
    """Return all worker-claim documents using constructor-backed accessors."""
    total = db.worker_claims.count()
    if total == 0:
        return []

    claims: list[dict[str, Any]] = []
    worker_ids = db.worker_claims.worker_id.collect(limit=total)
    for worker_id in worker_ids:
        claims.extend(db.worker_claims.worker_id.get.many(worker_id, limit=total))
    return claims


def _file_has_tagged_state(db: Database, file_id: str) -> bool:
    """Return whether a file currently has the tagged state edge."""
    return file_has_tagged_state(db, file_id)


def discover_next_file(
    db: Database,
) -> str | None:
    """Discover next untagged file.

    Uses file_states graph traversal to find files in the not_tagged state,
    excluding too_short and already-claimed files.

    Args:
        db: Database instance

    Returns:
        File _id or None if no work available

    """
    file_doc = discover_next_untagged_file(db, exclude_claimed=True)
    if file_doc:
        return str(file_doc["_id"])
    return None


def claim_file(db: Database, file_id: str, worker_id: str) -> bool:
    """Attempt to claim file for processing.

    Uses deterministic _key based on file._key to enforce uniqueness.
    ArangoDB document key uniqueness prevents duplicate claims.

    Args:
        db: Database instance
        file_id: Full file document _id (e.g., "library_files/12345")
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        True if claim successful, False if already claimed

    """
    try:
        db.worker_claims.insert(
            [
                {
                    "_key": _claim_key(file_id),
                    "file_id": file_id,
                    "worker_id": worker_id,
                    "claimed_at": now_ms().value,
                }
            ],
        )
    except DocumentInsertError:
        return False
    return True


def release_claim(db: Database, file_id: str) -> None:
    """Release claim on file (after processing or error).

    Args:
        db: Database instance
        file_id: Full file document _id

    """
    db.worker_claims.file_id.delete(file_id)


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
    health_docs = db.health.component_type.get.many("worker", limit=db.health.count())
    active_workers = {
        str(doc.get("component_id")) for doc in health_docs if int(doc.get("last_heartbeat", 0)) > heartbeat_cutoff
    }

    delete_ids: set[str] = set()
    for claim in all_claims:
        claim_id = str(claim["_id"])
        worker_id = str(claim["worker_id"])
        file_id = str(claim["file_id"])
        claim_type = claim.get("claim_type")

        if worker_id not in active_workers:
            delete_ids.add(claim_id)
            continue

        if claim_type == "reconcile":
            continue

        file_doc = get_file_by_id(db, file_id)
        if file_doc is None or _file_has_tagged_state(db, file_id):
            delete_ids.add(claim_id)

    if not delete_ids:
        return 0

    db.worker_claims.delete(list(delete_ids))
    return len(delete_ids)


def discover_and_claim_file(
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
        Claimed file _id or None if no work available or claim failed

    """
    file_id = discover_next_file(db)
    if not file_id:
        logger.debug("[Discovery] No files found needing processing (worker=%s)", worker_id)
        return None

    if claim_file(db, file_id, worker_id):
        logger.debug("[Discovery] Claimed %s for %s", file_id, worker_id)
        return file_id
    # Another worker claimed this file - caller should retry
    logger.debug("[Discovery] File %s already claimed, retrying discovery", file_id)
    return None


def get_active_claim_count(db: Database) -> int:
    """Get count of active claims.

    Args:
        db: Database instance

    Returns:
        Number of active claim documents

    """
    return db.worker_claims.count()


def release_claims_for_worker(db: Database, worker_id: str) -> list[str]:
    """Release all claims held by a specific worker.

    Used when a worker dies/crashes to free its claimed files for rediscovery.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        List of file_ids that were released

    """
    claims = db.worker_claims.worker_id.get.many(worker_id, limit=db.worker_claims.count())
    if not claims:
        return []

    db.worker_claims.delete([claim["_id"] for claim in claims])
    return [str(claim["file_id"]) for claim in claims]
