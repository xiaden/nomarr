"""Tag-reconciliation helpers extracted from legacy library-file persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_state_comp import get_stale_file_ids, transition_file_state
from nomarr.components.workers.worker_discovery_comp import try_insert_or_steal_claim
from nomarr.helpers.constants.file_states import (
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_STALE,
    STATE_TAGS_WRITTEN,
)
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def claim_files_for_reconciliation(
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
        The raw ``library_files`` documents that were successfully claimed for the
        worker.
    """
    stale_ids = get_stale_file_ids(db, library_id=library_id)
    if not stale_ids:
        return []

    candidates = [
        candidate
        for file_id in stale_ids
        if (candidate := cast("dict[str, Any] | None", db.library_files.get(_id=file_id))) is not None
    ]

    claimed: list[dict[str, Any]] = []
    now = now_ms().value
    for candidate in candidates:
        if len(claimed) >= batch_size:
            break

        file_id = str(candidate["_id"])
        file_key = str(candidate["_key"])
        claim_key = f"claim_reconcile_{file_key}"
        payload = {
            "_key": claim_key,
            "file_id": file_id,
            "worker_id": worker_id,
            "claimed_at": now,
            "claim_type": "reconcile",
        }

        if try_insert_or_steal_claim(db, payload, now, lease_ms):
            claimed.append(candidate)

    return claimed


def set_file_written(db: Database, file_key: str) -> None:
    """Advance projection-state edges after a successful tag write."""
    if file_key.startswith("library_files/"):
        file_id = file_key
    else:
        file_id = f"library_files/{file_key}"

    transition_file_state(db, [file_id], STATE_TAGS_NOT_WRITTEN, STATE_TAGS_WRITTEN)
    transition_file_state(db, [file_id], STATE_TAGS_STALE, STATE_TAGS_CURRENT)
    db.worker_claims.delete(file_id=file_id)


def release_claim(db: Database, file_key: str) -> None:
    """Release a reconciliation claim without changing projection state."""
    if file_key.startswith("library_files/"):
        file_id = file_key
    else:
        file_id = f"library_files/{file_key}"
    db.worker_claims.delete(file_id=file_id)


def count_files_needing_reconciliation(db: Database, library_id: str) -> int:
    """Count files that are still in the ``tags_stale`` state."""
    return len(get_stale_file_ids(db, library_id=library_id))
