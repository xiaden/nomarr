"""PG-targeted integration tests for the transactional song-hydration intent.

Exercises ``SongHydrationRepository.hydrate_song`` and
``hydrate_songs_batch`` against the shared ``pg_session`` fixture so the
multi-statement unit-of-work boundary is verified end-to-end across the
collaborating repositories (song / tag / song-tag / song-state).

Two integration-only invariants are asserted here that the SQLite unit tests
cover only in isolation:

* **Multi-statement atomicity** — a failure injected at the *final* write step
  (the state transition) rolls back every preceding write (tags, duration).
  This is the strongest proof that no partial hydration leaks.
* **Chunk commit boundaries** — a multi-chunk batch commits each chunk as one
  atomic unit: a failing chunk rolls back entirely while prior/remaining
  chunks still commit and are counted.

.. note::
   This suite runs on the SQLite-backed ``pg_session`` fixture from
   ``tests/integration/conftest.py`` (a temp-file SQLite database with
   ``Base.metadata.create_all``). It is NOT live PostgreSQL, and it does NOT
   claim a PostgreSQL startup gate: the corrected fresh-schema initialization
   against a real PostgreSQL instance is covered by the Phase 3 gate of
   ``TASK-tag-persistence-ownership-C-tests-and-verification`` (see P3-S1/P3-S2).
   These tests remain useful for fast repository behavior and transaction
   rollback semantics, but SQLite-only success must not be treated as evidence
   for PG-specific behavior or for a PG startup.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, select

from nomarr.helpers.constants.file_states import (
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_PROCESSED,
)
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.persistence.database.song_hydration_repo import SongHydrationRepository
from nomarr.persistence.database.song_repo import SongRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

_LIBRARY_NAMES = count(1)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _create_library_and_song(session, path: str = "/pgint/lib/test.mp3") -> tuple[int, int]:
    """Insert a library + song; return ``(library_id, song_id)``."""
    lib_r = session.execute(
        insert(Library).values(
            name=f"PG Int Lib {next(_LIBRARY_NAMES)}",
            path="/pgint/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    song_r = session.execute(
        insert(Song).values(
            library_id=lib_id,
            path=path,
            normalized_path=path,
            file_size=1000,
            modified_time=1000,
            duration_seconds=None,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    song_id = song_r.inserted_primary_key[0]
    return lib_id, song_id


def _make_input(
    song_id: int,
    *,
    parsed_nom_tags: Mapping[str, Sequence[str | int | float]] | None = None,
    entity_tags: Mapping[str, Sequence[str | int | float]] | None = None,
    metadata_cache: Mapping[str, str | int | float | list[str] | None] | None = None,
    duration_seconds: float | None = None,
) -> HydrateSongInput:
    """Build a HydrateSongInput, overriding fields as needed."""
    return HydrateSongInput(
        song_id=song_id,
        parsed_nom_tags=(parsed_nom_tags if parsed_nom_tags is not None else {"nom:mood-strict": ["happy"]}),
        entity_tags=entity_tags if entity_tags is not None else {"genre": ["rock"], "year": [1999]},
        metadata_cache=metadata_cache if metadata_cache is not None else {"artist": "The Test"},
        duration_seconds=duration_seconds,
    )


def _build_repo(session) -> SongHydrationRepository:
    """Build the hydration repo wired to collaborator repos on *session*."""
    return SongHydrationRepository(
        session=session,
        song_repo=SongRepository(session),
        tag_repo=TagRepository(session),
        song_tag_repo=SongTagRepository(session),
        song_state_repo=SongStateRepository(session),
    )


def _song_tags(session, song_id: int) -> set[tuple[str, str]]:
    """Return (name, value) tag pairs assigned to a song."""
    stmt = (
        select(Tag.__table__.c.name, Tag.__table__.c.value)
        .join(SongTag.__table__, SongTag.__table__.c.tag_id == Tag.__table__.c.id)
        .where(SongTag.__table__.c.song_id == song_id)
    )
    return {(r[0], r[1]) for r in session.execute(stmt)}


def _song_tag_rows(session, song_id: int) -> set[tuple[str, str, str]]:
    """Return complete ``(namespace, name, value)`` identity triples assigned to a song."""
    stmt = (
        select(Tag.__table__.c.namespace, Tag.__table__.c.name, Tag.__table__.c.value)
        .join(SongTag.__table__, SongTag.__table__.c.tag_id == Tag.__table__.c.id)
        .where(SongTag.__table__.c.song_id == song_id)
    )
    return {(r[0], r[1], r[2]) for r in session.execute(stmt)}


def _song_tag_edges(session, song_id: int) -> set[tuple[str, str, str, float, str]]:
    """Return ``(namespace, name, value, confidence, source)`` edges for a song (edge metadata)."""
    stmt = (
        select(
            Tag.__table__.c.namespace,
            Tag.__table__.c.name,
            Tag.__table__.c.value,
            SongTag.__table__.c.confidence,
            SongTag.__table__.c.source,
        )
        .join(SongTag.__table__, SongTag.__table__.c.tag_id == Tag.__table__.c.id)
        .where(SongTag.__table__.c.song_id == song_id)
    )
    return {(r[0], r[1], r[2], float(r[3]), str(r[4])) for r in session.execute(stmt)}


def _pending_song(session) -> int:
    """Create a not_hydrated+processed song with no tags yet."""
    state_repo = SongStateRepository(session)
    state_repo.bootstrap_states([])
    _, song_id = _create_library_and_song(session)
    state_repo.assign_state(song_id, STATE_PROCESSED)
    state_repo.assign_state(song_id, STATE_NOT_HYDRATED)
    return song_id


@pytest.mark.integration
@pytest.mark.requires_database
class TestHydrateSongPgAtomicity:
    """Multi-statement atomicity of ``hydrate_song`` (rollback on PG semantics)."""

    def test_failure_at_state_transition_rolls_back_all_preceding_writes(self, pg_session, monkeypatch) -> None:
        """Injecting a failure at the FINAL write step leaves tags/duration/state untouched.

        This is the strongest atomicity check: tags and duration are written
        before the state transition, so a failure there must roll them all back
        — proving a song is never left half-hydrated on PG transaction
        semantics.
        """
        song_id = _pending_song(pg_session)
        state_repo = SongStateRepository(pg_session)

        repo = _build_repo(pg_session)

        def _boom(*args, **kwargs):
            raise RuntimeError("injected state-transition failure")

        monkeypatch.setattr(repo._song_state_repo, "transition_to_hydrated", _boom)

        with pytest.raises(RuntimeError):
            repo.hydrate_song(_make_input(song_id, duration_seconds=321.0))

        # Nothing partial persisted: no tag edges, no duration, no hydrated state.
        assert _song_tags(pg_session, song_id) == set()
        states = state_repo.get_song_states(song_id)
        assert STATE_HYDRATED not in states
        assert STATE_NOT_HYDRATED in states
        assert STATE_PROCESSED in states
        duration = pg_session.execute(
            select(Song.__table__.c.duration_seconds).where(Song.__table__.c.id == song_id)
        ).scalar_one()
        assert duration is None

    def test_successful_hydrate_song_commits_tags_duration_state(self, pg_session) -> None:
        """A clean run persists tags, duration, and the hydrated transition."""
        song_id = _pending_song(pg_session)
        state_repo = SongStateRepository(pg_session)

        _build_repo(pg_session).hydrate_song(_make_input(song_id, duration_seconds=222.0))

        assert _song_tags(pg_session, song_id) == {
            ("nom:mood-strict", "happy"),
            ("genre", "rock"),
            ("year", "1999"),
        }
        states = state_repo.get_song_states(song_id)
        assert STATE_HYDRATED in states
        assert STATE_NOT_HYDRATED not in states
        assert STATE_PROCESSED in states
        duration = pg_session.execute(
            select(Song.__table__.c.duration_seconds).where(Song.__table__.c.id == song_id)
        ).scalar_one()
        assert duration == 222.0

    def test_hydrated_edges_carry_namespace_and_edge_metadata(self, pg_session) -> None:
        """Entity tags are ``default``, Nomarr tags ``nom``; confidence/source stay on edges."""
        song_id = _pending_song(pg_session)

        _build_repo(pg_session).hydrate_song(_make_input(song_id))

        # Complete identity triples: entity -> default, parsed nom -> nom.
        rows = _song_tag_rows(pg_session, song_id)
        assert ("default", "genre", "rock") in rows
        assert ("default", "year", "1999") in rows
        assert ("nom", "nom:mood-strict", "happy") in rows
        # Edge metadata (confidence/source) is read from song_tags, not tag rows.
        assert ("default", "genre", "rock", 1.0, "nomarr") in _song_tag_edges(pg_session, song_id)
        # The tags table remains identity-only.
        tag_columns = {col.name for col in Tag.__table__.c}
        assert not ({"confidence", "source", "tier", "created_at", "parent_tag_id"} & tag_columns)

    def test_same_name_value_across_namespaces_are_distinct_rows(self, pg_session) -> None:
        """Dedup uses the complete (namespace, name, value) key.

        ``genre=Rock`` as an entity tag (default) and as a parsed nom tag (nom)
        persist as two distinct identities with independent edges — never merged.
        """
        song_id = _pending_song(pg_session)

        _build_repo(pg_session).hydrate_song(
            _make_input(song_id, parsed_nom_tags={"genre": ["Rock"]}, entity_tags={"genre": ["Rock"]})
        )

        rows = _song_tag_rows(pg_session, song_id)
        assert ("default", "genre", "Rock") in rows
        assert ("nom", "genre", "Rock") in rows
        # Each complete identity maps to exactly one physical tags row.
        for ns in ("default", "nom"):
            count = pg_session.execute(
                select(Tag.__table__.c.id).where(
                    (Tag.__table__.c.namespace == ns)
                    & (Tag.__table__.c.name == "genre")
                    & (Tag.__table__.c.value == "Rock")
                )
            ).all()
            assert len(count) == 1


@pytest.mark.integration
@pytest.mark.requires_database
class TestHydrateSongsBatchPgChunks:
    """Chunk commit boundaries of ``hydrate_songs_batch`` (PG semantics)."""

    def test_failing_chunk_rolls_back_while_others_commit(self, pg_session) -> None:
        """Each chunk commits atomically; a failing chunk leaks nothing."""
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        _, s1 = _create_library_and_song(pg_session, path="/pgint/lib/ok1.mp3")
        _, s2 = _create_library_and_song(pg_session, path="/pgint/lib/ok2.mp3")
        _, s3 = _create_library_and_song(pg_session, path="/pgint/lib/ok3.mp3")

        # chunk_size=1: [s1] | [999999(missing)] | [s2] | [s3].
        # The missing-song chunk fails and rolls back; the rest commit.
        inputs = [
            _make_input(s1, parsed_nom_tags={"nom:c1": ["a"]}),
            _make_input(999999, parsed_nom_tags={"nom:c2": ["x"]}),
            _make_input(s2, parsed_nom_tags={"nom:c1": ["b"]}),
            _make_input(s3, parsed_nom_tags={"nom:c1": ["c"]}),
        ]

        committed = _build_repo(pg_session).hydrate_songs_batch(inputs, chunk_size=1)

        assert committed == 3
        states = state_repo.get_song_states
        assert STATE_HYDRATED in states(s1)
        assert STATE_HYDRATED in states(s2)
        assert STATE_HYDRATED in states(s3)
        # Failing chunk's writes rolled back.
        assert _song_tags(pg_session, 999999) == set()
        assert _song_tags(pg_session, s1) == {("nom:c1", "a"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s2) == {("nom:c1", "b"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s3) == {("nom:c1", "c"), ("genre", "rock"), ("year", "1999")}

    def test_multi_input_chunk_commits_as_one_unit(self, pg_session, monkeypatch) -> None:
        """A failure mid-chunk rolls back ALL inputs in that same chunk."""
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        _, s1 = _create_library_and_song(pg_session, path="/pgint/lib/unit1.mp3")
        _, s2 = _create_library_and_song(pg_session, path="/pgint/lib/unit2.mp3")

        repo = _build_repo(pg_session)

        def _boom(*args, **kwargs):
            raise RuntimeError("injected failure")

        # Fail the relationship-replace step for the whole 2-input chunk.
        monkeypatch.setattr(repo._song_tag_repo, "replace_song_tags_batch", _boom)

        # chunk_size=100 → both inputs share one chunk; both must roll back.
        committed = repo.hydrate_songs_batch(
            [
                _make_input(s1, parsed_nom_tags={"nom:u": ["1"]}),
                _make_input(s2, parsed_nom_tags={"nom:u": ["2"]}),
            ],
            chunk_size=100,
        )

        assert committed == 0
        assert _song_tags(pg_session, s1) == set()
        assert _song_tags(pg_session, s2) == set()
        assert STATE_HYDRATED not in state_repo.get_song_states(s1)
        assert STATE_HYDRATED not in state_repo.get_song_states(s2)
