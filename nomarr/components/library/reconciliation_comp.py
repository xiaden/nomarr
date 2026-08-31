"""Tag-reconciliation helpers extracted from legacy library-file persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import get_stale_song_ids, transition_song_state
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.persistence.db import Database


def claim_files_for_reconciliation(
    db: Database,
    library: Library,
    worker_id: str,
    batch_size: int = 100,
    lease_ms: int = 60000,
) -> list[Song]:
    """Claim stale files for projection reconciliation.

    Args:
        db: Database handle used to read stale library files and manage worker claims.
        library: Domain ``Library`` whose stale files should be considered.
        worker_id: Worker identity recorded on each claim so the claiming worker can
            own the lease or replace an expired one.
        batch_size: Maximum number of stale file candidates to claim in this call.
            Defaults to 100.
        lease_ms: Claim lease duration in milliseconds. Existing claims older than
            this threshold are treated as expired and can be replaced. Defaults to
            60000.

    Returns:
        The domain ``Song`` values that were successfully claimed for the
        worker (typed as ``claim_type="reconcile"``).

    """
    # overlap: mechanism-A natural-name threading (P4-S8) - this file is under
    # concurrent reconciliation cleanup; preserve adjacent hunks.
    stale_ids = get_stale_song_ids(db, library)
    library_song_ids = {song.song_id for song in db.library.list_songs(library)}
    pending_ids = [song_id for song_id in db.app.song_ids_with_state(STATE_NOT_WRITTEN) if song_id in library_song_ids]
    reconcile_ids = list(dict.fromkeys([*stale_ids, *pending_ids]))
    if not reconcile_ids:
        return []

    claimed: list[Song] = []
    now = now_ms().value
    for song_id in reconcile_ids:
        if len(claimed) >= batch_size:
            break

        song = db.library.get_song(song_id)
        if song is None:
            continue
        identity = db.library.resolve_song_identity(song_id)
        if identity is None:
            continue
        claim = WorkerClaim(
            identity=WorkerClaimIdentity(song=identity, worker_id=worker_id, claim_type="reconcile"),
            claimed_at_ms=now,
        )
        if db.app.add_claim(claim, lease_ms=lease_ms):
            claimed.append(song)

    return claimed


def set_file_written(db: Database, file_key: str, worker_id: str) -> None:
    """Advance processing state transitions after a successful tag write.

    PostgreSQL uses integer IDs; file_key is the string representation of the ID.
    """
    file_id = int(file_key)
    transition_song_state(db, [file_id], STATE_NOT_WRITTEN, STATE_WRITTEN)
    if STATE_TAGS_NOT_FRESH in db.app.song_state_membership(file_id):
        transition_song_state(db, [file_id], STATE_TAGS_NOT_FRESH, STATE_TAGS_CURRENT)
    identity = db.library.resolve_song_identity(file_id)
    if identity is not None:
        db.app.remove_claim(WorkerClaimIdentity(song=identity, worker_id=worker_id, claim_type="reconcile"))


def release_claim(db: Database, file_key: str, worker_id: str) -> None:
    """Release a reconciliation claim without changing projection state.

    PostgreSQL uses integer IDs; file_key is the string representation of the ID.
    """
    file_id = int(file_key)
    identity = db.library.resolve_song_identity(file_id)
    if identity is None:
        return
    db.app.remove_claim(WorkerClaimIdentity(song=identity, worker_id=worker_id, claim_type="reconcile"))


def count_files_needing_reconciliation(db: Database, library: Library) -> int:
    """Count files whose database tag projection needs writing to disk."""
    stale_ids = get_stale_song_ids(db, library)
    library_song_ids = {song.song_id for song in db.library.list_songs(library)}
    pending_ids = [song_id for song_id in db.app.song_ids_with_state(STATE_NOT_WRITTEN) if song_id in library_song_ids]
    return len(set(stale_ids).union(pending_ids))
