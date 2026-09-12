"""Real-boundary evidence for create-only song-state initialization (Q3-A P1-S3).

This module exercises the real ``LibrarySongsDb`` facade over real repositories
and a live PostgreSQL session (never a mocked facade):

- a genuinely new song row is initialized with the canonical negative states;
- re-upserting an existing row preserves every existing state assignment and
  does not re-run ``initialize_song_states`` (the Q3-A regression);
- a mid-batch failure rolls back every document in that batch, proving the
  scan batch is a single transaction rather than N per-doc transactions.

This module is collected by the ``database-tests`` job (single pytest invocation,
``-m requires_database``; listed verbatim in
``tests/unit/architecture/capability-manifest.json`` ``pytest_paths`` and
``exact_command``). The job does NOT provide ``NOMARR_TEST_DATABASE_URL``, so the
module is skip-only in CI today — wired-not-run, i.e. ``CI_DEFERRED``; it never
claims CI execution or ``CI_PASS``. Docker/PostgreSQL and the env var are also
unavailable locally, so the module is environment-skipped here as well.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.persistence.database.song_state_repo import (
    _NEGATIVE_STATE_VERTICES,
    SongStateRepository,
)
from nomarr.persistence.db import Database
from nomarr.persistence.models.library import Library as LibraryModel
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state import SongState
from nomarr.persistence.models.song_state_assignment import SongStateAssignment

_PG_URL = os.environ.get("NOMARR_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_database,
    pytest.mark.skipif(
        not _PG_URL,
        reason=(
            "requires a live PostgreSQL server via NOMARR_TEST_DATABASE_URL; "
            "Docker/PostgreSQL unavailable locally so this evidence is environment-blocked"
        ),
    ),
]


@pytest.fixture
def engine():
    eng = create_engine(_PG_URL or "", future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def database():
    db = Database(url=_PG_URL or "")
    try:
        yield db
    finally:
        db.close()


def _insert_library(engine) -> tuple[str, str]:
    library_uuid = str(uuid.uuid4())
    name = f"q3a-{library_uuid[:12]}"
    with Session(engine) as session:
        session.add(
            LibraryModel(
                library_uuid=library_uuid,
                name=name,
                path=f"/music/{name}",
                library_type="music",
                created_at=1000,
                updated_at=1000,
            )
        )
        session.commit()
    return library_uuid, name


def _delete_library(engine, library_uuid: str) -> None:
    with Session(engine) as session:
        library_id = session.scalar(select(LibraryModel.id).where(LibraryModel.library_uuid == library_uuid))
        if library_id is not None:
            session.query(Song).filter(Song.library_id == library_id).delete()
        session.query(LibraryModel).filter(LibraryModel.library_uuid == library_uuid).delete()
        session.commit()


def _identity(library_uuid: str, name: str) -> LibraryIdentity:
    return LibraryIdentity(library_uuid=library_uuid, name=name)


def _command(
    library: LibraryIdentity,
    path: str,
    *,
    file_size: int = 123,
    modified_time: int = 456,
) -> SongUpsertInput:
    return SongUpsertInput(
        library=library,
        path=path,
        scan=SongScanUpdate(
            normalized_path=path.lstrip("/"),
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=12.5,
            is_valid=True,
        ),
    )


def _song_id(engine, library_uuid: str, path: str) -> int:
    with Session(engine) as session:
        library_id = session.scalar(select(LibraryModel.id).where(LibraryModel.library_uuid == library_uuid))
        assert library_id is not None
        song_id = session.scalar(select(Song.id).where(Song.library_id == library_id, Song.path == path))
        assert song_id is not None
        return int(song_id)


def _state_names(engine, song_id: int) -> set[str]:
    with Session(engine) as session:
        rows = session.execute(
            select(SongState.name)
            .join(SongStateAssignment, SongStateAssignment.state_id == SongState.id)
            .where(SongStateAssignment.song_id == song_id)
        ).all()
        return {str(name) for (name,) in rows}


def test_new_song_initializes_canonical_negative_states(database, engine) -> None:
    library_uuid, name = _insert_library(engine)
    identity = _identity(library_uuid, name)
    try:
        database.library.add_songs_to_library_batch([_command(identity, "/music/new.mp3")])

        song_id = _song_id(engine, library_uuid, "/music/new.mp3")
        assert _state_names(engine, song_id) == set(_NEGATIVE_STATE_VERTICES)
    finally:
        _delete_library(engine, library_uuid)


def test_existing_song_reupsert_preserves_existing_states(database, engine) -> None:
    library_uuid, name = _insert_library(engine)
    identity = _identity(library_uuid, name)
    song = SongIdentity(library=identity, normalized_path="music/existing.mp3")
    try:
        database.library.add_songs_to_library_batch([_command(identity, "/music/existing.mp3")])
        # Advance one axis away from its negative pole.
        database.app.transition_song_states([song], "not_processed", "processed")

        song_id = _song_id(engine, library_uuid, "/music/existing.mp3")
        assert "processed" in _state_names(engine, song_id)
        assert "not_processed" not in _state_names(engine, song_id)

        # Re-upsert the existing row: states must be preserved, not reinitialized.
        database.library.add_songs_to_library_batch(
            [_command(identity, "/music/existing.mp3", file_size=999, modified_time=888)]
        )

        states = _state_names(engine, song_id)
        assert "processed" in states
        assert "not_processed" not in states
        # Untouched axes remain initialized.
        assert "not_scanned" in states
    finally:
        _delete_library(engine, library_uuid)


def test_batch_failure_rolls_back_all_documents(database, engine, monkeypatch) -> None:
    library_uuid, name = _insert_library(engine)
    identity = _identity(library_uuid, name)
    docs = [
        _command(identity, "/music/rollback-a.mp3"),
        _command(identity, "/music/rollback-b.mp3"),
    ]

    def _fail(_self, _song_ids, **_kwargs) -> None:
        raise RuntimeError("injected state-init failure")

    monkeypatch.setattr(SongStateRepository, "initialize_song_states", _fail)

    try:
        with pytest.raises(RuntimeError, match="injected state-init failure"):
            database.library.add_songs_to_library_batch(docs)

        with Session(engine) as session:
            library_id = session.scalar(select(LibraryModel.id).where(LibraryModel.library_uuid == library_uuid))
            assert library_id is not None
            remaining = session.scalars(select(Song.path).where(Song.library_id == library_id)).all()
            assert list(remaining) == []
    finally:
        _delete_library(engine, library_uuid)


def test_mixed_batch_preserves_order_and_initializes_only_new(database, engine, monkeypatch) -> None:
    """An interleaved new/existing batch keeps order and is create-only.

    (a) the returned ``SongIdentity`` list is in input order; (b) the existing
    song's advanced state is preserved and not reinitialized; (c) the genuinely
    new songs receive the canonical negative states; (d) ``initialize_song_states``
    is invoked only for the new ids.
    """
    library_uuid, name = _insert_library(engine)
    identity = _identity(library_uuid, name)
    existing = SongIdentity(library=identity, normalized_path="music/mixed-existing.mp3")
    try:
        # Seed the pre-existing song and advance one axis away from its negative pole.
        database.library.add_songs_to_library_batch([_command(identity, "/music/mixed-existing.mp3")])
        database.app.transition_song_states([existing], "not_processed", "processed")
        existing_song_id = _song_id(engine, library_uuid, "/music/mixed-existing.mp3")

        init_calls: list[list[int]] = []
        original_initialize = SongStateRepository.initialize_song_states

        def _record(self, song_ids, **kwargs):
            init_calls.append(list(song_ids))
            return original_initialize(self, song_ids, **kwargs)

        monkeypatch.setattr(SongStateRepository, "initialize_song_states", _record)

        commands = [
            _command(identity, "/music/mixed-new-a.mp3"),
            _command(identity, "/music/mixed-existing.mp3", file_size=999, modified_time=888),
            _command(identity, "/music/mixed-new-b.mp3"),
        ]

        result = database.library.add_songs_to_library_batch(commands)

        # (a) input order is preserved, including across the interleaved existing row.
        assert result == [
            SongIdentity(library=identity, normalized_path="music/mixed-new-a.mp3"),
            SongIdentity(library=identity, normalized_path="music/mixed-existing.mp3"),
            SongIdentity(library=identity, normalized_path="music/mixed-new-b.mp3"),
        ]

        # (b) the existing song's advanced state survives the re-upsert.
        existing_states = _state_names(engine, existing_song_id)
        assert "processed" in existing_states
        assert "not_processed" not in existing_states

        # (c) each new song is initialized with the canonical negative states.
        new_a_id = _song_id(engine, library_uuid, "/music/mixed-new-a.mp3")
        new_b_id = _song_id(engine, library_uuid, "/music/mixed-new-b.mp3")
        assert _state_names(engine, new_a_id) == set(_NEGATIVE_STATE_VERTICES)
        assert _state_names(engine, new_b_id) == set(_NEGATIVE_STATE_VERTICES)

        # (d) state initialization was invoked only for the genuinely new ids.
        initialized_ids = {song_id for call in init_calls for song_id in call}
        assert initialized_ids == {new_a_id, new_b_id}
        assert existing_song_id not in initialized_ids
    finally:
        _delete_library(engine, library_uuid)
