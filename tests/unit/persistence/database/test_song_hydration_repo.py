"""Unit tests for SongHydrationRepository (transactional song hydration).

Covers single-song and batched hydration, bounded bulk statements (via a
``before_cursor_execute`` statement counter — proving no N+1 tag/entity
lookups), and the edge cases in the hydrate contract: empty batches,
duplicate song ids, duplicate tag values, missing songs, and repeated
identical inputs (idempotency).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, insert, select

from nomarr.helpers.constants.file_states import (
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_PROCESSED,
)
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.helpers.exceptions import EntityNotFoundError
from nomarr.persistence.database.song_hydration_repo import SongHydrationRepository
from nomarr.persistence.database.song_repo import SongRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import Engine


def _create_library_and_song(session, path: str = "/hydrate/lib/test.mp3") -> tuple[int, int]:
    """Helper: insert a library and song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name="Hydrate Lib",
            path="/hydrate/lib",
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


class _StatementCounter:
    """Counts DB statements via a ``before_cursor_execute`` event listener."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.count += 1

    def detach(self) -> None:
        event.remove(self.engine, "before_cursor_execute", self._on_execute)


def _song_tags(session, song_id: int) -> set[tuple[str, str]]:
    """Return (name, value) tag pairs assigned to a song."""
    stmt = (
        select(Tag.__table__.c.name, Tag.__table__.c.value)
        .join(SongTag.__table__, SongTag.__table__.c.tag_id == Tag.__table__.c.id)
        .where(SongTag.__table__.c.song_id == song_id)
    )
    return {(r[0], r[1]) for r in session.execute(stmt)}


@pytest.mark.unit
@pytest.mark.integration
class TestHydrateSong:
    """Single-song hydrate_song behavior."""

    def test_hydrate_song_writes_tags_and_state(self, pg_session) -> None:
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        state_repo.assign_state(song_id, STATE_PROCESSED)
        state_repo.assign_state(song_id, STATE_NOT_HYDRATED)

        _build_repo(pg_session).hydrate_song(_make_input(song_id, duration_seconds=200.0))

        tags = _song_tags(pg_session, song_id)
        assert ("nom:mood-strict", "happy") in tags
        assert ("genre", "rock") in tags
        assert ("year", "1999") in tags
        states = SongStateRepository(pg_session).get_song_states(song_id)
        assert STATE_HYDRATED in states
        assert STATE_NOT_HYDRATED not in states
        assert STATE_PROCESSED in states  # unrelated axis preserved
        row = pg_session.execute(select(Song.__table__).where(Song.__table__.c.id == song_id)).fetchone()
        assert row.duration_seconds == 200.0

    def test_hydrate_song_duration_is_one_shot(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        SongRepository(pg_session).update_song(song_id, {"duration_seconds": 111.0})

        _build_repo(pg_session).hydrate_song(_make_input(song_id, duration_seconds=200.0))

        row = pg_session.execute(select(Song.__table__).where(Song.__table__.c.id == song_id)).fetchone()
        assert row.duration_seconds == 111.0  # never overwrites existing duration

    def test_hydrate_song_no_duration_keeps_null(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        _build_repo(pg_session).hydrate_song(_make_input(song_id, duration_seconds=None))

        row = pg_session.execute(select(Song.__table__).where(Song.__table__.c.id == song_id)).fetchone()
        assert row.duration_seconds is None

    def test_hydrate_song_missing_song_raises(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        with pytest.raises(EntityNotFoundError):
            _build_repo(pg_session).hydrate_song(_make_input(999999))

    def test_hydrate_song_is_idempotent(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        repo = _build_repo(pg_session)
        inp = _make_input(song_id)

        repo.hydrate_song(inp)
        repo.hydrate_song(inp)

        assert _song_tags(pg_session, song_id) == {
            ("nom:mood-strict", "happy"),
            ("genre", "rock"),
            ("year", "1999"),
        }
        assert STATE_HYDRATED in SongStateRepository(pg_session).get_song_states(song_id)


@pytest.mark.unit
@pytest.mark.integration
class TestHydrateSongsBatch:
    """Batch hydration: bounded statements + contract edge cases."""

    def _bootstrap_and_songs(self, pg_session, n: int) -> list[int]:
        SongStateRepository(pg_session).bootstrap_states([])
        song_ids = []
        for i in range(n):
            _, song_id = _create_library_and_song(pg_session, path=f"/hydrate/lib/song{i}.mp3")
            song_ids.append(song_id)
        return song_ids

    def test_empty_batch_returns_zero(self, pg_session) -> None:
        result = _build_repo(pg_session).hydrate_songs_batch([])
        assert result == 0

    def test_duplicate_song_ids_committed_once(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        inp = _make_input(song_id, parsed_nom_tags={"nom:dup": ["a", "a"]})

        committed = _build_repo(pg_session).hydrate_songs_batch([inp, inp])

        assert committed == 2
        # Both inputs hydrated the same song; tags written once.
        assert _song_tags(pg_session, song_id) == {
            ("nom:dup", "a"),
            ("genre", "rock"),
            ("year", "1999"),
        }

    def test_duplicate_tag_values_deduped(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        inp = _make_input(song_id, entity_tags={"genre": ["rock", "rock"]})

        _build_repo(pg_session).hydrate_songs_batch([inp])

        # replace_song_tags_batch dedupes by (song_id, tag_id) — single edge.
        assert _song_tags(pg_session, song_id) == {
            ("genre", "rock"),
            ("nom:mood-strict", "happy"),
        }

    def test_missing_song_skips_its_chunk_but_commits_others(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song1 = _create_library_and_song(pg_session, path="/hydrate/lib/ok1.mp3")
        _, song2 = _create_library_and_song(pg_session, path="/hydrate/lib/ok2.mp3")
        inputs = [_make_input(song1), _make_input(999999), _make_input(song2)]

        # chunk_size=1 → each input is its own atomic chunk.
        committed = _build_repo(pg_session).hydrate_songs_batch(inputs, chunk_size=1)

        assert committed == 2
        assert STATE_HYDRATED in SongStateRepository(pg_session).get_song_states(song1)
        assert STATE_HYDRATED in SongStateRepository(pg_session).get_song_states(song2)
        # Missing song's chunk rolled back → song 999999 not written.
        assert _song_tags(pg_session, 999999) == set()

    def test_repeated_identical_inputs_idempotent(self, pg_session) -> None:
        SongStateRepository(pg_session).bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        inp = _make_input(song_id)

        repo = _build_repo(pg_session)
        first = repo.hydrate_songs_batch([inp, inp])
        second = repo.hydrate_songs_batch([inp, inp])

        assert first == 2 and second == 2
        assert _song_tags(pg_session, song_id) == {
            ("nom:mood-strict", "happy"),
            ("genre", "rock"),
            ("year", "1999"),
        }
        assert STATE_HYDRATED in SongStateRepository(pg_session).get_song_states(song_id)

    def test_statement_count_is_bounded_within_a_chunk(self, pg_engine, pg_session) -> None:
        """The statement count stays constant as inputs grow within one chunk.

        If the batch degenerated to per-tag/per-song lookups, the statement
        count would scale with the number of songs/tags.  It must instead stay
        bounded (a handful of bulk statements per chunk).
        """
        SongStateRepository(pg_session).bootstrap_states([])
        song_ids_small = self._bootstrap_and_songs(pg_session, 2)
        song_ids_large = self._bootstrap_and_songs(pg_session, 8)

        def _run(song_ids: list[int]) -> int:
            counter = _StatementCounter(pg_engine)
            try:
                repo = _build_repo(pg_session)
                inputs = [
                    _make_input(
                        sid,
                        parsed_nom_tags={"nom:mood-strict": ["happy"], "nom:energy": ["high"]},
                        entity_tags={"genre": ["rock"], "year": [1999], "label": ["Lab"]},
                    )
                    for sid in song_ids
                ]
                repo.hydrate_songs_batch(inputs, chunk_size=100)  # one chunk
                return counter.count
            finally:
                counter.detach()

        small_count = _run(song_ids_small)
        large_count = _run(song_ids_large)

        # 8 songs must not need substantially more statements than 2 songs —
        # both are handled by the same bounded set of bulk statements.
        assert large_count <= small_count + 3
        # Sanity: more than one song actually ran (not a degenerate short-circuit).
        assert large_count >= 3


@pytest.mark.unit
@pytest.mark.integration
class TestHydrateSongRollback:
    """Injected failures must roll back the entire unit — no partial writes."""

    def _make_pending_song(self, pg_session) -> int:
        """Create a not_hydrated+processed song with no tags yet."""
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        state_repo.assign_state(song_id, STATE_PROCESSED)
        state_repo.assign_state(song_id, STATE_NOT_HYDRATED)
        assert _song_tags(pg_session, song_id) == set()
        return song_id

    @pytest.mark.parametrize(
        ("inject_on", "attr"),
        [
            ("tag insert", "_tag_repo"),
            ("relationship replace", "_song_tag_repo"),
            ("duration update", "_song_repo"),
            ("state transition", "_song_state_repo"),
        ],
    )
    def test_rollback_when_step_fails(self, pg_session, monkeypatch, inject_on: str, attr: str) -> None:
        """A failure in any write step leaves tags/state/duration unchanged."""
        song_id = self._make_pending_song(pg_session)
        state_repo = SongStateRepository(pg_session)

        repo = _build_repo(pg_session)
        collaborator = getattr(repo, attr)

        def _boom(*args, **kwargs):
            raise RuntimeError(f"injected {inject_on} failure")

        if inject_on == "tag insert":
            monkeypatch.setattr(collaborator, "get_or_create_tags_batch", _boom)
        elif inject_on == "relationship replace":
            monkeypatch.setattr(collaborator, "replace_song_tags_batch", _boom)
        elif inject_on == "duration update":
            monkeypatch.setattr(collaborator, "set_duration_if_unset", _boom)
        elif inject_on == "state transition":
            monkeypatch.setattr(collaborator, "transition_to_hydrated", _boom)

        with pytest.raises(RuntimeError):
            repo.hydrate_song(_make_input(song_id, duration_seconds=999.0))

        # Nothing partial persisted: no tags, no duration, no hydrated state.
        assert _song_tags(pg_session, song_id) == set()
        states = state_repo.get_song_states(song_id)
        assert STATE_HYDRATED not in states
        assert STATE_NOT_HYDRATED in states
        assert STATE_PROCESSED in states
        duration = pg_session.execute(
            select(Song.__table__.c.duration_seconds).where(Song.__table__.c.id == song_id)
        ).scalar_one()
        assert duration is None

    def test_metadata_cache_payload_causes_no_sql_write(self, pg_engine, pg_session) -> None:
        """A non-empty metadata_cache adds no statement (ADR-045: no cache columns)."""
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        # Pre-create the tag vertices once so both measured runs see identical
        # tag state (no insert-during-run difference masks the cache assertion).
        _, warmup_id = _create_library_and_song(pg_session, path="/hydrate/cache/warmup.mp3")
        _build_repo(pg_session).hydrate_song(_make_input(warmup_id, duration_seconds=1.0))

        def _run(metadata_cache: dict) -> int:
            _, song_id = _create_library_and_song(pg_session)
            counter = _StatementCounter(pg_engine)
            try:
                _build_repo(pg_session).hydrate_song(
                    _make_input(song_id, metadata_cache=metadata_cache, duration_seconds=200.0)
                )
                return counter.count
            finally:
                counter.detach()

        baseline = _run({})
        with_cache = _run({"artist": "A", "album": "B", "year": 2020})

        # The cache payload must not emit any additional statement.
        assert with_cache == baseline


@pytest.mark.unit
@pytest.mark.integration
class TestHydrateIdempotencyGaps:
    """Idempotency gaps not already covered by the Phase 2 suite."""

    def test_empty_no_tag_input_transitions_state_without_tag_writes(self, pg_session) -> None:
        """Empty/no-tag input: no tag writes, but state still transitions."""
        state_repo = SongStateRepository(pg_session)
        state_repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)
        state_repo.assign_state(song_id, STATE_NOT_HYDRATED)

        _build_repo(pg_session).hydrate_song(
            _make_input(song_id, parsed_nom_tags={}, entity_tags={}, metadata_cache={}, duration_seconds=None)
        )

        # No tag writes at all.
        assert _song_tags(pg_session, song_id) == set()
        # But the song still transitions to hydrated.
        states = state_repo.get_song_states(song_id)
        assert STATE_HYDRATED in states
        assert STATE_NOT_HYDRATED not in states


@pytest.mark.unit
@pytest.mark.integration
class TestHydrateBatchBoundedBulk:
    """Bounded-bulk performance across more than one chunk."""

    def test_chunk_commit_boundaries_on_multi_chunk_failure(self, pg_session) -> None:
        """Each chunk commits atomically; a failing chunk doesn't leak its writes."""
        SongStateRepository(pg_session).bootstrap_states([])
        _, s1 = _create_library_and_song(pg_session)
        _, s2 = _create_library_and_song(pg_session)
        _, s3 = _create_library_and_song(pg_session)
        _, s4 = _create_library_and_song(pg_session)
        _, s5 = _create_library_and_song(pg_session)
        _, s6 = _create_library_and_song(pg_session)

        # chunk_size=3 → 7 inputs split as [0,1,2],[3,4,5],[6]. Chunk 1 = s1..s3,
        # chunk 2 starts with a missing song (999999) so it fails and rolls back
        # its s4/s5 writes, chunk 3 = s6.
        inputs = [
            _make_input(s1, parsed_nom_tags={"nom:c1": ["a"]}),
            _make_input(s2, parsed_nom_tags={"nom:c1": ["b"]}),
            _make_input(s3, parsed_nom_tags={"nom:c1": ["c"]}),
            _make_input(999999, parsed_nom_tags={"nom:c2": ["x"]}),
            _make_input(s4, parsed_nom_tags={"nom:c2": ["y"]}),
            _make_input(s5, parsed_nom_tags={"nom:c2": ["z"]}),
            _make_input(s6, parsed_nom_tags={"nom:c3": ["w"]}),
        ]

        committed = _build_repo(pg_session).hydrate_songs_batch(inputs, chunk_size=3)

        # Chunk 1 (3) + chunk 3 (1) commit; chunk 2 (3) fails entirely.
        assert committed == 4
        states = SongStateRepository(pg_session).get_song_states
        assert STATE_HYDRATED in states(s1)
        assert STATE_HYDRATED in states(s2)
        assert STATE_HYDRATED in states(s3)
        assert STATE_HYDRATED in states(s6)
        # Chunk 2's writes rolled back — s4/s5 never hydrated.
        assert STATE_HYDRATED not in states(s4)
        assert STATE_HYDRATED not in states(s5)
        # Each committed song carries exactly its chunk's edges + entity defaults.
        assert _song_tags(pg_session, s1) == {("nom:c1", "a"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s2) == {("nom:c1", "b"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s3) == {("nom:c1", "c"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s6) == {("nom:c3", "w"), ("genre", "rock"), ("year", "1999")}
        assert _song_tags(pg_session, s4) == set()
        assert _song_tags(pg_session, s5) == set()
        assert _song_tags(pg_session, 999999) == set()

    def test_statement_count_scales_with_chunks_not_inputs(self, pg_engine, pg_session) -> None:
        """More inputs beyond one chunk cost bounded chunks, not per-input work."""
        SongStateRepository(pg_session).bootstrap_states([])

        def _run(inputs: list[HydrateSongInput], chunk_size: int) -> int:
            counter = _StatementCounter(pg_engine)
            try:
                _build_repo(pg_session).hydrate_songs_batch(inputs, chunk_size=chunk_size)
                return counter.count
            finally:
                counter.detach()

        ids = []
        for _ in range(7):
            _, sid = _create_library_and_song(pg_session)
            ids.append(sid)

        def make_input(sid: int) -> HydrateSongInput:
            return _make_input(
                sid,
                parsed_nom_tags={"nom:p": ["v"]},
                entity_tags={"genre": ["rock"], "year": [1999]},
            )

        # 4 inputs = 2 chunks of 3; 7 inputs = 3 chunks of 3.
        four = [make_input(sid) for sid in ids[:4]]
        seven = [make_input(sid) for sid in ids]

        four_count = _run(four, chunk_size=3)
        seven_count = _run(seven, chunk_size=3)

        # Statement count is bounded: growing by a whole chunk adds at most one
        # bounded chunk's statements, never inputs x tags.
        assert seven_count >= four_count
        assert seven_count <= four_count + 15
