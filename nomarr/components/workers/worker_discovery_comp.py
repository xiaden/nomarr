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
_TAGGED_STATE_ID = "file_states/tagged"


def _claim_key(file_id: str) -> str:
    """Build the deterministic worker-claim key for a file."""
    file_key = file_id.split("/")[1] if "/" in file_id else file_id
    return f"claim_{file_key}"


def _get_all_claims(db: Database) -> list[dict[str, Any]]:
    """Return all worker claims via the application facade."""
    return cast("list[dict[str, Any]]", db.app.list_claims())


def discover_next_file(
    db: Database,
) -> str | None:
    """Discover next untagged file using file_states graph traversal, excluding too_short and claimed files."""
    file_doc = discover_next_untagged_file(db, exclude_claimed=True)
    if file_doc:
        return str(file_doc["_id"])
    return None


def claim_file(db: Database, file_id: str, worker_id: str) -> bool:
    """Attempt to claim file for processing. Uses deterministic _key to enforce uniqueness."""
    payload = {
        "_key": _claim_key(file_id),
        "file_id": file_id,
        "worker_id": worker_id,
        "claimed_at": now_ms().value,
    }
    try:
        db.app.add_claim(payload)
    except DuplicateKeyError:
        return False
    return True


def release_claim(db: Database, file_id: str) -> None:
    """Release claim on file after processing or error."""
    db.app.remove_claim(file_id)


def try_insert_or_steal_claim(
    db: Database,
    payload: dict[str, Any],
    now: int,
    lease_ms: int,
) -> bool:
    """Try to insert a claim, stealing it if the existing one is expired."""
    try:
        db.app.add_claim(payload)
    except DuplicateKeyError:
        file_id = str(payload["file_id"])
        existing_claim = next(
            (claim for claim in _get_all_claims(db) if str(claim.get("file_id")) == file_id),
            None,
        )
        if existing_claim is None:
            try:
                db.app.add_claim(payload)
            except DuplicateKeyError:
                return False
            return True

        claimed_at = int(existing_claim.get("claimed_at", 0))
        if claimed_at > now - lease_ms:
            return False

        db.app.remove_claim(file_id)
        try:
            db.app.add_claim(payload)
        except DuplicateKeyError:
            return False
        return True
    return True


def cleanup_stale_claims(db: Database, heartbeat_timeout_ms: int) -> int:
    """Remove claims from inactive workers and completed/ineligible files."""
    all_claims = _get_all_claims(db)
    if not all_claims:
        return 0

    heartbeat_cutoff = now_ms().value - heartbeat_timeout_ms
    health_docs = cast("list[dict[str, Any]]", db.app.list_worker_health())
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

    stale_file_ids: set[str] = set()
    candidate_file_ids = sorted({str(claim["file_id"]) for claim in active_ml_claims})
    if candidate_file_ids:
        file_docs = cast("list[dict[str, Any]]", db.library.list_files_by_ids(candidate_file_ids))
        existing_file_ids = {str(doc["_id"]) for doc in file_docs if "_id" in doc}

        tagged_file_ids = {
            str(file_doc["_id"])
            for file_doc in cast("list[dict[str, Any]]", db.app.list_file_docs_in_state(_TAGGED_STATE_ID))
            if "_id" in file_doc and str(file_doc["_id"]) in candidate_file_ids
        }
        stale_file_ids = {
            file_id for file_id in candidate_file_ids if file_id not in existing_file_ids or file_id in tagged_file_ids
        }

    removed = 0
    if inactive_worker_ids:
        removed += db.app.remove_claims(worker_ids=sorted(inactive_worker_ids))
    if stale_file_ids:
        removed += db.app.remove_claims(file_ids=sorted(stale_file_ids))
    return removed


def discover_and_claim_file(
    db: Database,
    worker_id: str,
) -> str | None:
    """Discover and atomically claim the next available file for processing."""
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
    """Get count of active claims."""
    return db.app.count_claims()


def release_claims_for_worker(db: Database, worker_id: str) -> list[str]:
    """Release all claims held by a specific worker (used on worker death/crash)."""
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
