"""Worker discovery component.

Core discovery and claiming logic for discovery-based workers.
Workers query library_files directly instead of polling a queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def discover_next_file(db: Database) -> str | None:
    """Discover next unprocessed file.

    Queries library_files for files with needs_tagging=1 and is_valid=1.
    Uses deterministic ordering by _key for consistent work distribution.

    Args:
        db: Database instance

    Returns:
        File _id or None if no work available

    """
    file_doc = db.library_files.discover_next_unprocessed_file()
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
    return db.worker_claims.try_claim_file(file_id, worker_id)


def release_claim(db: Database, file_id: str) -> None:
    """Release claim on file (after processing or error).

    Args:
        db: Database instance
        file_id: Full file document _id

    """
    db.worker_claims.release_claim(file_id)


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
    return db.worker_claims.cleanup_all_stale_claims(heartbeat_timeout_ms)


def discover_and_claim_file(db: Database, worker_id: str) -> str | None:
    """Discover and claim the next available file for processing.

    Combined operation that:
    1. Discovers next unprocessed file
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
        logger.debug("[Discovery] No files need processing")
        return None

    if claim_file(db, file_id, worker_id):
        logger.debug("[Discovery] Claimed file %s for worker %s", file_id, worker_id)
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
    return db.worker_claims.get_active_claim_count()


def release_claims_for_worker(db: Database, worker_id: str) -> list[str]:
    """Release all claims held by a specific worker.

    Used when a worker dies/crashes to free its claimed files for rediscovery.

    Args:
        db: Database instance
        worker_id: Worker identifier (e.g., "worker:tag:0")

    Returns:
        List of file_ids that were released

    """
    return db.worker_claims.release_claims_for_worker(worker_id)

