"""Distributed lock helpers for platform workflows and components."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.helpers.dataclasses.app_dataclasses import LockEntry
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def acquire_distributed_lock(
    db: Database,
    lock_type: str,
    resource_id: str,
    holder: str,
    ttl_seconds: int,
) -> bool:
    """Acquire a distributed lock when absent, expired, or already owned by the holder."""
    now = float(now_ms().value)
    expires_at = now + float(ttl_seconds * 1000)

    existing = db.app.get_lock(lock_type, resource_id)
    if existing is not None:
        if existing.expires_at >= now and existing.holder != holder:
            return False
        db.app.remove_lock(lock_type, resource_id)

    try:
        if not db.app.acquire_lock(
            LockEntry(
                lock_type=lock_type,
                resource_id=resource_id,
                holder=holder,
                expires_at=expires_at,
                acquired_at=now,
                status="active",
            )
        ):
            return False
    except DuplicateEntityError:
        return False
    return True


def release_distributed_lock(db: Database, lock_type: str, resource_id: str, holder: str) -> bool:
    """Release a distributed lock only when it is still owned by the holder."""
    existing = db.app.get_lock(lock_type, resource_id)
    if existing is None or existing.holder != holder:
        return False

    db.app.remove_lock(lock_type, resource_id)
    remaining = db.app.get_lock(lock_type, resource_id)
    return remaining is None or remaining.holder != holder


def reap_stale_locks(db: Database, worker_id: str, stale_after_ms: int) -> None:
    """Delete stale vector-promotion locks older than the provided age threshold."""
    stale_threshold = float(now_ms().value - stale_after_ms)
    stale_locks = db.app.list_locks()
    for lock in stale_locks:
        if lock.lock_type != "vector_promotion":
            continue
        if lock.acquired_at >= stale_threshold:
            continue

        current = db.app.get_lock(lock.lock_type, lock.resource_id)
        if current is None or current.lock_type != "vector_promotion":
            continue
        if current.acquired_at >= stale_threshold:
            continue

        db.app.remove_lock(lock.lock_type, lock.resource_id)
        resource_id = lock.resource_id
        logger.warning("[locks] %s reaped stale promotion lock for %s", worker_id, resource_id)
