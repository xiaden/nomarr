"""Tag-reconciliation helpers extracted from legacy library-file persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_state_comp import get_stale_file_ids, transition_file_state
from nomarr.components.workers.worker_discovery_comp import try_insert_or_steal_claim
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


async def claim_files_for_reconciliation(
    db: Database,
    library_id: str,
    worker_id: str,
    batch_size: int = 100,
    lease_ms: int = 60000,
) -> list[dict[str, Any]]:
    """Claim stale files for projection reconciliation.

    Args:
        db: Database handle used to read stale library files and manage worker claims.
        library_id: Library whose stale files should be considered for reconciliation.
        worker_id: Worker identity recorded on each claim so the claiming worker can
            own the lease or replace an expired one.
        batch_size: Maximum number of stale file candidates to claim in this call.
            Defaults to 100.
        lease_ms: Claim lease duration in milliseconds. Existing claims older than
            this threshold are treated as expired and can be stolen. Defaults to
            60000.

    Returns:
        The raw song documents that were successfully claimed for the
        worker.

    """
    stale_ids = get_stale_file_ids(db, library_id=library_id)
    if not stale_ids:
        return []

    candidates = [
        candidate
        for file_id in stale_ids
        if (candidate := cast("dict[str, Any] | None", await db.library.get_file(file_id))) is not None
    ]

    claimed: list[dict[str, Any]] = []
    now = now_ms().value
    for candidate in candidates:
        if len(claimed) >= batch_size:
            break

        file_id = str(candidate["id"])
        file_key = str(candidate["id"])
        claim_key = f"claim_reconcile_{file_key}"
        payload = {
            "key": claim_key,
            "file_id": file_id,
            "worker_id": worker_id,
            "claimed_at": now,
            "claim_type": "reconcile",
        }

        if try_insert_or_steal_claim(db, payload, now, lease_ms):
            claimed.append(candidate)

    return claimed


async def set_file_written(db: Database, file_key: str) -> None:
    """Advance processing state transitions after a successful tag write.

    PostgreSQL uses integer IDs; file_key is the string representation of the ID.
    """
    file_id = int(file_key)
    await transition_file_state(db, [file_id], STATE_NOT_WRITTEN, STATE_WRITTEN)
    await transition_file_state(db, [file_id], STATE_TAGS_NOT_FRESH, STATE_TAGS_CURRENT)
    await db.application.release_claim(file_id)


async def release_claim(db: Database, file_key: str) -> None:
    """Release a reconciliation claim without changing projection state.

    PostgreSQL uses integer IDs; file_key is the string representation of the ID.
    """
    file_id = int(file_key)
    await db.application.release_claim(file_id)


async def count_files_needing_reconciliation(db: Database, library_id: str) -> int:
    """Count files that are still in the ``tags_not_fresh`` state."""
    return len(await get_stale_file_ids(db, library_id=library_id))
