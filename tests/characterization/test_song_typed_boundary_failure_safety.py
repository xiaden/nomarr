"""Plan D typed-boundary failure-safety oracle on real PostgreSQL.

Plan D (TASK-song-row-mirror-leaks-into-domain-D) Phase 1 real-DB proof of the
``add_song_to_library(SongUpsertInput)`` canonical typed-upsert handoff boundary:

- The song-row upsert (``song_repo.upsert_songs_for_library``) and the state
  initialization (``song_state_repo.initialize_song_states``) share ONE
  facade-owned transaction: both are invoked with ``commit=False`` and the facade
  issues exactly one ``self._session.commit()``. A state-init failure therefore
  rolls the whole transaction back — NO song row and NO state assignments
  persist — and the facade surfaces the error rather than compensating with a
  delete. This is the **atomic-rollback** boundary: re-running the idempotent
  intent completes the state bootstrap. It IS all-or-none across (song-row,
  states) — that single-transaction contract is the honest contract Plan E/M/O
  must rely on.

Relocation (destination-conflict + stale-locator rollback leaving source locator,
scan metadata, and associations unchanged) is owned and proven on real PostgreSQL
by ``tests/characterization/test_song_move_atomic_intent.py`` (Plan C) — this file
**links** that oracle rather than duplicating it. Tag / claim / pipeline / ML
aggregate boundaries are linked to their external owners (TagRef successor B-E
pending; worker-claims canonical ``db.app.add_claim`` surface; ML typed
write-boundary commit ``0dce610f`` green).

PostgreSQL-only (relies on real commit/rollback semantics), so this module is
marked ``characterization`` + ``requires_database``. It runs in the CI
``database-tests`` job through the testcontainers characterization fixtures
(``tests/characterization/conftest.py`` provides the migrated PostgreSQL session).
Docker is not available in the authoring workspace, so this file cannot be
executed here; the environment blocker is reported honestly (unavailable
infrastructure is not PASS).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongRemoval,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.exceptions import DatabaseStateError
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state_assignment import SongStateAssignment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nomarr.persistence.db import Database

_SONG_TABLE = Song.__table__
_ASSIGNMENT_TABLE = SongStateAssignment.__table__


def _count_songs_by_normalized_path(session: Session, library_id: int, normalized_path: str) -> int:
    stmt = (
        select(func.count())
        .select_from(_SONG_TABLE)
        .where(
            _SONG_TABLE.c.library_id == library_id,
            _SONG_TABLE.c.normalized_path == normalized_path,
        )
    )
    return int(session.execute(stmt).scalar_one())


def _count_state_assignments(session: Session, library_id: int, normalized_path: str) -> int:
    """Count song_state_assignments for the song at (library_id, normalized_path)."""
    song_id_stmt = select(_SONG_TABLE.c.id).where(
        _SONG_TABLE.c.library_id == library_id,
        _SONG_TABLE.c.normalized_path == normalized_path,
    )
    song_id = session.execute(song_id_stmt).scalar_one_or_none()
    if song_id is None:
        return -1  # song absent → sentinel so a caller can tell "no song" from "no states"
    stmt = select(func.count()).select_from(_ASSIGNMENT_TABLE).where(_ASSIGNMENT_TABLE.c.song_id == song_id)
    return int(session.execute(stmt).scalar_one())


def _library_storage_id(session: Session, name: str) -> int:
    from nomarr.persistence.models.library import Library as LibraryModel

    lib_table = LibraryModel.__table__
    stmt = select(lib_table.c.id).where(lib_table.c.name == name)
    return int(session.execute(stmt).scalar_one())


def _song_row_id(session: Session, library_id: int, normalized_path: str) -> int | None:
    """Private storage id of the song at (library_id, normalized_path), if present."""
    stmt = select(_SONG_TABLE.c.id).where(
        _SONG_TABLE.c.library_id == library_id,
        _SONG_TABLE.c.normalized_path == normalized_path,
    )
    return session.execute(stmt).scalar_one_or_none()


@pytest.mark.characterization
@pytest.mark.requires_database
class TestAddSongToLibraryAtomicRollbackBoundary:
    """The canonical typed-upsert handoff is all-or-none across (song-row, states).

    Proves on real PostgreSQL that the song-row upsert and the state
    initialization share one facade-owned transaction: a state-init failure rolls
    the whole transaction back so the row is absent with no state assignments,
    the facade surfaces the error without a compensating delete, and a retry of
    the idempotent intent completes the bootstrap.
    """

    def test_state_init_failure_rolls_back_row_and_retry_recovers(
        self,
        db: Database,
        inference_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lib = db.library.create_library(Library(name="FSLib", root_path="/tmp/fslib"))
        assert lib.library_uuid is not None  # persistence mints the immutable identity
        library_id = _library_storage_id(inference_session, "FSLib")
        try:
            library_identity = LibraryIdentity(library_uuid=lib.library_uuid, name="FSLib", root_path="/tmp/fslib")

            def _cmd(path: str, normalized_path: str) -> SongUpsertInput:
                return SongUpsertInput(
                    library=library_identity,
                    path=path,
                    scan=SongScanUpdate(
                        normalized_path=normalized_path,
                        file_size=1024,
                        modified_time=5000,
                        duration_seconds=180.0,
                        is_valid=True,
                        scanned_at=9000,
                    ),
                )

            # 1) A normal typed upsert bootstraps initial (negative) states.
            db.library.add_song_to_library(_cmd("/tmp/fslib/ok.flac", "ok.flac"))
            assert _count_songs_by_normalized_path(inference_session, library_id, "ok.flac") == 1
            assert _count_state_assignments(inference_session, library_id, "ok.flac") > 0

            # 2) Inject a state-init failure inside the shared transaction (the
            # shipped call passes the keyword-only commit=False).
            def _state_init_fails(song_ids, *, commit=False):  # type: ignore[no-untyped-def]
                raise DatabaseStateError("injected state-init failure")

            monkeypatch.setattr(db.library.songs._song_state_repo, "initialize_song_states", _state_init_fails)

            with pytest.raises(DatabaseStateError):
                db.library.add_song_to_library(_cmd("/tmp/fslib/partial.flac", "partial.flac"))

            # The whole facade-owned transaction rolled back: neither the song ROW
            # nor any state assignments persist (file's song-absent sentinel is -1).
            assert _count_songs_by_normalized_path(inference_session, library_id, "partial.flac") == 0
            assert _count_state_assignments(inference_session, library_id, "partial.flac") == -1

            # 3) Re-run the idempotent intent (no injected failure) → recovery.
            monkeypatch.undo()
            db.library.add_song_to_library(_cmd("/tmp/fslib/partial.flac", "partial.flac"))
            assert _count_songs_by_normalized_path(inference_session, library_id, "partial.flac") == 1
            assert _count_state_assignments(inference_session, library_id, "partial.flac") > 0
        finally:
            db.library.remove_library(lib)


@pytest.mark.characterization
@pytest.mark.requires_database
class TestRetryIdempotentAndNoResurrection:
    """P2-S1 real-PostgreSQL proofs for retry idempotency and deletion semantics.

    Proves on real PG that re-issuing the typed upsert intent does not duplicate
    the row or its state assignments, and that a removed song stays removed — a
    re-issued ``remove_song`` is a ``False`` miss and a later upsert of the same
    locator creates a NEW row (fresh private storage id), never a resurrection of
    the removed row (ADR-048 clause 6 / CONTRACTS).
    """

    def test_reissuing_upsert_is_idempotent_no_duplicate_row_or_state(
        self,
        db: Database,
        inference_session: Session,
    ) -> None:
        lib = db.library.create_library(Library(name="FSRetry", root_path="/tmp/fsretry"))
        assert lib.library_uuid is not None  # persistence mints the immutable identity
        library_id = _library_storage_id(inference_session, "FSRetry")
        try:
            library_identity = LibraryIdentity(library_uuid=lib.library_uuid, name="FSRetry", root_path="/tmp/fsretry")

            def _cmd() -> SongUpsertInput:
                return SongUpsertInput(
                    library=library_identity,
                    path="/tmp/fsretry/retry.flac",
                    scan=SongScanUpdate(
                        normalized_path="retry.flac",
                        file_size=1024,
                        modified_time=5000,
                        duration_seconds=180.0,
                        is_valid=True,
                        scanned_at=9000,
                    ),
                )

            db.library.add_song_to_library(_cmd())
            states_after_first = _count_state_assignments(inference_session, library_id, "retry.flac")
            assert _count_songs_by_normalized_path(inference_session, library_id, "retry.flac") == 1
            assert states_after_first > 0

            # Re-issue the SAME typed command: the row is updated in place (ON
            # CONFLICT upsert), never duplicated, and state assignments are not
            # re-added (idempotent negative-vertex bootstrap).
            db.library.add_song_to_library(_cmd())

            assert _count_songs_by_normalized_path(inference_session, library_id, "retry.flac") == 1
            assert _count_state_assignments(inference_session, library_id, "retry.flac") == states_after_first
        finally:
            db.library.remove_library(lib)

    def test_removed_song_stays_removed_and_readd_is_new_row(
        self,
        db: Database,
        inference_session: Session,
    ) -> None:
        lib = db.library.create_library(Library(name="FSRemoval", root_path="/tmp/fsremoval"))
        assert lib.library_uuid is not None  # persistence mints the immutable identity
        library_id = _library_storage_id(inference_session, "FSRemoval")
        try:
            library_identity = LibraryIdentity(
                library_uuid=lib.library_uuid, name="FSRemoval", root_path="/tmp/fsremoval"
            )

            def _cmd() -> SongUpsertInput:
                return SongUpsertInput(
                    library=library_identity,
                    path="/tmp/fsremoval/gone.flac",
                    scan=SongScanUpdate(
                        normalized_path="gone.flac",
                        file_size=1024,
                        modified_time=5000,
                        duration_seconds=180.0,
                        is_valid=True,
                        scanned_at=9000,
                    ),
                )

            db.library.add_song_to_library(_cmd())
            row_id_before = _song_row_id(inference_session, library_id, "gone.flac")
            assert row_id_before is not None

            removal = SongRemoval(song_identity=SongIdentity(library=library_identity, normalized_path="gone.flac"))
            assert db.library.remove_song(removal) is True
            # Removed: no row, no state assignments, locator no longer resolves.
            assert _count_songs_by_normalized_path(inference_session, library_id, "gone.flac") == 0
            assert _count_state_assignments(inference_session, library_id, "gone.flac") == -1
            assert db.library.get_song(SongIdentity(library=library_identity, normalized_path="gone.flac")) is None
            # Re-issuing remove after success is a deterministic False miss.
            assert db.library.remove_song(removal) is False

            # A later upsert of the SAME locator is a NEW row — fresh private id,
            # NOT a resurrection of the removed row.
            db.library.add_song_to_library(_cmd())
            assert _count_songs_by_normalized_path(inference_session, library_id, "gone.flac") == 1
            row_id_after = _song_row_id(inference_session, library_id, "gone.flac")
            assert row_id_after is not None and row_id_after != row_id_before
        finally:
            db.library.remove_library(lib)
