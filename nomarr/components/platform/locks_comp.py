"""Distributed lock helpers for platform workflows and components."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.exceptions import DuplicateKeyError

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def make_lock_reference(lock_type: str, resource_id: str) -> str:
    """Build the deterministic lock reference stored in the app lock facade."""
    return f"{lock_type}:{resource_id}"


def acquire_distributed_lock(
    db: Database,
    lock_type: str,
    resource_id: str,
    holder: str,
    ttl_seconds: int,
) -> bool:
    """Acquire a distributed lock when absent, expired, or already owned by the holder."""
    reference = make_lock_reference(lock_type, resource_id)
    now = float(now_ms().value)
    expires_at = now + float(ttl_seconds * 1000)

    existing = cast("dict[str, Any] | None", db.app.get_lock(reference))
    if existing is not None:
        existing_expires_at = float(existing.get("expires_at", 0.0))
        if existing_expires_at >= now and existing.get("holder") != holder:
            return False
        db.app.remove_lock(reference)

    payload = {
        "document_reference": reference,
        "lock_type": lock_type,
        "holder": holder,
        "expires_at": expires_at,
        "acquired_at": now,
        "status": "active",
    }
    try:
        db.app.add_lock(payload)
    except DuplicateKeyError:
        return False
    return True


def release_distributed_lock(db: Database, lock_type: str, resource_id: str, holder: str) -> bool:
    """Release a distributed lock only when it is still owned by the holder."""
    reference = make_lock_reference(lock_type, resource_id)
    existing = cast("dict[str, Any] | None", db.app.get_lock(reference))
    if existing is None or existing.get("holder") != holder:
        return False

    db.app.remove_lock(reference)
    remaining = cast("dict[str, Any] | None", db.app.get_lock(reference))
    return remaining is None or remaining.get("holder") != holder


def reap_stale_locks(db: Database, worker_id: str, stale_after_ms: int) -> None:
    """Delete stale vector-promotion locks older than the provided age threshold."""
    stale_threshold = float(now_ms().value - stale_after_ms)
    stale_locks = db.app.list_locks()
    for lock in stale_locks:
        if lock.get("lock_type") != "vector_promotion":
            continue
        acquired_at = float(lock.get("acquired_at", 0.0))
        if acquired_at >= stale_threshold:
            continue

        reference = str(lock["document_reference"])
        current = cast("dict[str, Any] | None", db.app.get_lock(reference))
        if current is None:
            continue
        if current.get("lock_type") != "vector_promotion":
            continue
        current_acquired_at = float(current.get("acquired_at", 0.0))
        if current_acquired_at >= stale_threshold:
            continue

        resource_id = reference.split(":", maxsplit=1)[1]
        db.app.remove_lock(reference)
        logger.warning("[%s] Reaped stale promotion lock for %s", worker_id, resource_id)
