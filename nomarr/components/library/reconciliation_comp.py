"""Tag-reconciliation helpers extracted from legacy library-file persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
    from nomarr.persistence.db import Database


def claim_files_for_reconciliation(
    db: Database,
    library: Library,
    worker_id: str,
    batch_size: int = 100,
    lease_ms: int = 60000,
) -> list[SongStateCandidate]:
    """Claim stale or pending songs as typed candidates addressed by semantic locators."""
    library_identity = library.library_uuid
    if library_identity is None:
        return []
    candidates = [
        *db.library.list_songs_with_state(
            STATE_TAGS_NOT_FRESH, library=LibraryIdentity(library_identity, library.name, library.root_path)
        ),
        *db.library.list_songs_with_state(
            STATE_NOT_WRITTEN, library=LibraryIdentity(library_identity, library.name, library.root_path)
        ),
    ]
    claimed: list[SongStateCandidate] = []
    now = now_ms().value
    for candidate in dict.fromkeys(candidates):
        if len(claimed) >= batch_size:
            break
        claim = WorkerClaim(
            identity=WorkerClaimIdentity(song=candidate.identity, worker_id=worker_id, claim_type="reconcile"),
            claimed_at_ms=now,
        )
        if db.app.add_claim(claim, lease_ms=lease_ms):
            claimed.append(candidate)
    return claimed


def set_file_written(db: Database, song: SongIdentity, worker_id: str) -> None:
    """Advance processing state after a successful tag write."""
    transition_song_state(db, [song], STATE_NOT_WRITTEN, STATE_WRITTEN)
    if STATE_TAGS_NOT_FRESH in db.app.song_state_membership(song):
        transition_song_state(db, [song], STATE_TAGS_NOT_FRESH, STATE_TAGS_CURRENT)
    db.app.remove_claim(WorkerClaimIdentity(song=song, worker_id=worker_id, claim_type="reconcile"))


def release_claim(db: Database, song: SongIdentity, worker_id: str) -> None:
    """Release a reconciliation claim addressed by its semantic locator."""
    db.app.remove_claim(WorkerClaimIdentity(song=song, worker_id=worker_id, claim_type="reconcile"))


def count_files_needing_reconciliation(db: Database, library: Library) -> int:
    """Count locator-addressed songs whose database projection needs writing."""
    if library.library_uuid is None:
        return 0
    library_identity = LibraryIdentity(library.library_uuid, library.name, library.root_path)
    stale = db.library.list_songs_with_state(STATE_TAGS_NOT_FRESH, library=library_identity)
    pending = db.library.list_songs_with_state(STATE_NOT_WRITTEN, library=library_identity)
    return len({candidate.identity for candidate in [*stale, *pending]})
