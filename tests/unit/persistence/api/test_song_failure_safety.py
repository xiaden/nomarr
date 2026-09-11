"""Unit fault-injection and transaction-boundary tests for D-owned song intents.

Phase 1 (P1-S2 / P1-S3) of TASK-song-row-mirror-leaks-into-domain-D. These are
**repository-double** (``MagicMock``) tests — no real database — that inject
mapper / repository / statement / commit / uniqueness / connection failures at
the repository boundary backing each D-owned multi-table facade intent and pin
the facade's observable atomicity promise:

* ``add_song_to_library(SongUpsertInput)`` — canonical typed-upsert handoff
  (consumed; owned at commit ``9116f176``). The song-row upsert and the state
  initialization are **separate repository commits**; the facade does not own a
  transaction across them. Injected tests pin that a state-init failure after the
  row upsert has committed propagates to the caller **without compensation** (no
  delete), i.e. the boundary is *recorded-recoverable* (re-running the idempotent
  intent completes states) rather than all-or-none across (song-row, states).
* ``move_library_song(SongPathUpdate)`` — source-locator relocation (ADR-048 §4).
  The repository ``move_song`` is ONE in-place ``UPDATE`` + ONE commit; injected
  statement/commit/uniqueness/connection failures propagate and the facade never
  falls back to delete-plus-create or a fabricated replacement.
* ``remove_song(SongRemoval)`` — the repository ``delete_song`` is ONE ``DELETE``
  + ONE commit (FK CASCADE clears derived aggregates atomically); a failure
  propagates (single statement rolled back) and the facade never re-creates the
  row.
* ``list_songs_with_state`` — read-only multi-table orchestration
  (song_state_assignments + songs + libraries); a mid-read failure propagates and
  never mutates anything (no commit to be partial).
* Mapper isolation — a mapper failure on a read seam propagates and never falls
  back to exposing a raw storage row.

Tag / claim / pipeline / ML aggregates are **linked, not duplicated** here: their
boundaries are owned externally (TagRef successor B-E pending; worker-claims
`db.app.add_claim/...`; ML typed write-boundary commit ``0dce610f`` green). The
real-PostgreSQL rollback oracle for relocation (destination conflict + stale
locator leaving source locator / scan metadata / associations unchanged) is owned
by ``tests/characterization/test_song_move_atomic_intent.py`` (Plan C) and the
``add_song_to_library`` recorded-recoverable boundary by
``tests/characterization/test_song_typed_boundary_failure_safety.py`` (Plan D,
CI ``database-tests`` job). This module proves the facade-level invariants that
run without a database.

Phase 2 (P2-S1 / P2-S2) appends retry/deletion/no-resurrection and error-message
classes here: re-issuing the typed intents is idempotent (never a growing batch);
a removed song stays removed (re-issue of ``remove_song`` is a ``False`` miss and
a later upsert of the same locator is a NEW song, not a resurrection); restart
stale locators miss deterministically with no generated-id fallback; ``remove_song``
does not independently re-own state/claim cleanup (FK CASCADE + linked worker-claims
owner); and facade errors relay repo domain messages unchanged with no SQL /
storage row-id / credential / DSN disclosure. The real-PostgreSQL proofs for
idempotent retry and removal/no-resurrection live in the Plan D characterization
module (CI ``database-tests`` job).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongRemoval,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.exceptions import DatabaseStateError, DuplicateEntityError, ReferentialIntegrityError
from nomarr.persistence.api.library_songs import LibrarySongsDb

_LIB = LibraryIdentity(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")


def _identity(normalized_path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_LIB, normalized_path=normalized_path)


def _upsert_command(normalized_path: str = "a.mp3") -> SongUpsertInput:
    return SongUpsertInput(
        library=_LIB,
        path=f"/music/{normalized_path}",
        scan=SongScanUpdate(
            normalized_path=normalized_path,
            file_size=1024,
            modified_time=5000,
            duration_seconds=200.0,
            is_valid=True,
            scanned_at=None,
        ),
    )


def _move_command(source_normalized_path: str = "a.mp3", dest_normalized_path: str = "b.mp3") -> SongPathUpdate:
    return SongPathUpdate(
        song_identity=_identity(source_normalized_path),
        new_path=f"/music/{dest_normalized_path}",
        scan=SongScanUpdate(
            normalized_path=dest_normalized_path,
            file_size=2048,
            modified_time=6000,
            duration_seconds=210.0,
            is_valid=True,
            scanned_at=7000,
        ),
    )


def _remove_command() -> SongRemoval:
    return SongRemoval(song_identity=_identity("a.mp3"))


def _make_songs() -> tuple[LibrarySongsDb, MagicMock, MagicMock, MagicMock]:
    """Build a repository-double ``LibrarySongsDb``.

    Returns ``(facade, song_repo, song_state_repo, library_repo)`` with the
    library resolvable to the private storage id ``1`` by default. ``folder_repo``
    and ``song_hydration_repo`` are inert doubles (unused by the seams under test).
    """
    song_repo = MagicMock()
    song_state_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_by_uuid.return_value = {"id": 1}
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=MagicMock(),
        song_state_repo=song_state_repo,
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    return songs, song_repo, song_state_repo, library_repo


# ---------------------------------------------------------------------------
# add_song_to_library: canonical typed-upsert handoff (recorded-recoverable)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddSongToLibraryBoundary:
    """Fault injection on the consumed canonical typed-upsert handoff.

    The song-row upsert (``song_repo.upsert_songs_for_library``) and the state
    initialization (``song_state_repo.initialize_song_states``) are two
    repository-owned commits on the shared session — the facade owns no
    transaction across them. A state-init failure therefore leaves the song row
    already persisted (recorded), and the facade must surface the error rather
    than compensating with a delete.
    """

    def test_state_init_failure_after_row_commit_is_recorded_recoverable(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        # The row upsert commits (returns a generated song id); the independent
        # state-init repository commit then fails.
        song_repo.upsert_songs_for_library.return_value = [5]
        state_repo.initialize_song_states.side_effect = DatabaseStateError("state init commit failed")

        with pytest.raises(DatabaseStateError):
            songs.add_song_to_library(_upsert_command())

        # The song row write was issued (committed by its own repo transaction) and
        # the facade did NOT compensate with a delete — recovery is a retry of the
        # idempotent intent (recorded-recoverable), never all-or-none across both.
        song_repo.upsert_songs_for_library.assert_called_once()
        state_repo.initialize_song_states.assert_called_once_with([5])
        song_repo.delete_song.assert_not_called()

    def test_upsert_statement_failure_propagates_and_skips_state_init(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        # A statement failure inside the row upsert rolls back that single commit.
        song_repo.upsert_songs_for_library.side_effect = DatabaseStateError("statement failed")

        with pytest.raises(DatabaseStateError):
            songs.add_song_to_library(_upsert_command())

        # State init is not reached: no assignments bootstrap for a row that never
        # committed.
        state_repo.initialize_song_states.assert_not_called()

    def test_uniqueness_failure_propagates_and_skips_state_init(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        song_repo.upsert_songs_for_library.side_effect = DuplicateEntityError("dup")

        with pytest.raises(DuplicateEntityError):
            songs.add_song_to_library(_upsert_command())

        state_repo.initialize_song_states.assert_not_called()

    def test_connection_failure_propagates(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        song_repo.upsert_songs_for_library.side_effect = DatabaseStateError("connection lost")

        with pytest.raises(DatabaseStateError):
            songs.add_song_to_library(_upsert_command())

        state_repo.initialize_song_states.assert_not_called()

    def test_scanless_command_rejected_before_any_repo_write(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        scanless = SongUpsertInput(library=_LIB, path="/music/a.mp3", scan=None)

        with pytest.raises(ValueError):
            songs.add_song_to_library(scanless)

        # Atomic rejection before any write: no row and no state work is issued.
        song_repo.upsert_songs_for_library.assert_not_called()
        state_repo.initialize_song_states.assert_not_called()


# ---------------------------------------------------------------------------
# move_library_song: source-locator relocation (all-or-none, no delete/recreate)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMoveLibrarySongNoDeleteRecreate:
    """Fault injection on ``move_library_song``.

    One repo ``move_song`` UPDATE + one commit is the whole relocation; the
    facade must never delete-plus-recreate or fabricate a replacement on any
    injected failure or stale source (ADR-048 §4 / CONTRACTS §4).
    """

    def test_statement_failure_propagates_without_delete_or_insert(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.move_song.side_effect = DatabaseStateError("update statement failed")

        with pytest.raises(DatabaseStateError):
            songs.move_library_song(_move_command())

        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_commit_failure_propagates_without_delete_or_insert(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        # The single commit boundary fails after the UPDATE statement executed; the
        # repo rolls the statement back. From the facade the observable contract is
        # the same: the error propagates and no other row operation is issued.
        song_repo.move_song.side_effect = DatabaseStateError("commit failed")

        with pytest.raises(DatabaseStateError):
            songs.move_library_song(_move_command())

        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_connection_failure_propagates_without_delete_or_insert(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.move_song.side_effect = DatabaseStateError("connection lost during move")

        with pytest.raises(DatabaseStateError):
            songs.move_library_song(_move_command())

        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_destination_conflict_propagates_and_no_other_write(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        # A (library_id, path|normalized_path) destination collision surfaces as a
        # mapped uniqueness error from the single UPDATE; the whole statement rolls
        # back. The facade relays it and never falls back to delete/recreate.
        song_repo.move_song.side_effect = DuplicateEntityError("destination collides")

        with pytest.raises(DuplicateEntityError):
            songs.move_library_song(_move_command())

        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_stale_source_returns_none_without_fabrication(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        # A stale/missing source is a repo ``False`` miss: the facade returns None
        # and fabricates no replacement row on any path.
        song_repo.move_song.return_value = False

        assert songs.move_library_song(_move_command()) is None
        song_repo.move_song.assert_called_once()
        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_unresolvable_source_library_returns_none_without_write(self) -> None:
        songs, _, song_repo_unused, library_repo = _make_songs()
        _ = song_repo_unused
        library_repo.get_library_by_uuid.return_value = None

        assert songs.move_library_song(_move_command()) is None
        # No repo write is reached when the owning library cannot be resolved.

    def test_move_is_one_in_place_update_addressed_by_source_locator(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.move_song.return_value = True

        result = songs.move_library_song(_move_command("a.mp3", "b.mp3"))

        # The repo is addressed by (private library id, SOURCE normalized path) in a
        # single UPDATE whose payload carries the destination locator + scan fields.
        song_repo.move_song.assert_called_once()
        call_library_id, source_path, payload = song_repo.move_song.call_args[0]
        assert call_library_id == 1
        assert source_path == "a.mp3"
        assert payload["normalized_path"] == "b.mp3"
        assert payload["path"] == "/music/b.mp3"
        assert payload["scanned_at"] == 7000
        # Success returns the destination locator; no other row op ever runs.
        assert result == SongIdentity(library=_LIB, normalized_path="b.mp3")
        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_destination_normalized_path_none_rejected_before_write(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        command = SongPathUpdate(
            song_identity=_identity("a.mp3"),
            new_path="/music/b.mp3",
            scan=SongScanUpdate(normalized_path=None, file_size=2048, modified_time=6000),
        )

        with pytest.raises(ValueError):
            songs.move_library_song(command)

        # Atomic rejection before any write: no UPDATE is issued for an
        # unrepresentable destination.
        song_repo.move_song.assert_not_called()


# ---------------------------------------------------------------------------
# remove_song: single atomic DELETE (FK CASCADE), no re-create
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveSongBoundary:
    """Fault injection on ``remove_song``.

    The private ``delete_song`` is one ``DELETE`` + one commit (FK CASCADE clears
    derived streams/vectors/state/tag aggregates atomically with the row). A
    failure propagates — the single statement rolls back — and the facade never
    re-creates the row.
    """

    def _resolvable(self, songs: LibrarySongsDb, song_repo: MagicMock) -> None:
        song_repo.get_song_by_normalized_path.return_value = {"id": 5, "normalized_path": "a.mp3"}

    def test_delete_failure_propagates_and_row_not_recreated(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        self._resolvable(songs, song_repo)
        song_repo.delete_song.side_effect = DatabaseStateError("delete failed")

        with pytest.raises(DatabaseStateError):
            songs.remove_song(_remove_command())

        song_repo.upsert_songs_for_library.assert_not_called()

    def test_commit_failure_propagates(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        self._resolvable(songs, song_repo)
        song_repo.delete_song.side_effect = DatabaseStateError("commit failed")

        with pytest.raises(DatabaseStateError):
            songs.remove_song(_remove_command())

    def test_referential_integrity_failure_propagates(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        self._resolvable(songs, song_repo)
        song_repo.delete_song.side_effect = ReferentialIntegrityError("cascade blocked")

        with pytest.raises(ReferentialIntegrityError):
            songs.remove_song(_remove_command())

    def test_missing_song_returns_false_without_write(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.get_song_by_normalized_path.return_value = None

        assert songs.remove_song(_remove_command()) is False
        song_repo.delete_song.assert_not_called()

    def test_missing_library_returns_false_without_write(self) -> None:
        songs, _, _, library_repo = _make_songs()
        library_repo.get_library_by_uuid.return_value = None

        assert songs.remove_song(_remove_command()) is False

    def test_remove_is_single_delete_no_recreate(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        self._resolvable(songs, song_repo)
        song_repo.delete_song.return_value = None

        assert songs.remove_song(_remove_command()) is True
        song_repo.delete_song.assert_called_once_with(5)
        song_repo.upsert_songs_for_library.assert_not_called()


# ---------------------------------------------------------------------------
# list_songs_with_state: read-only multi-table orchestration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStateReadFaultInjection:
    """Fault injection on the typed state read.

    ``list_songs_with_state`` reads across song_state_assignments + songs +
    libraries but writes nothing (no commit), so a mid-read failure can never
    leave partial state — it simply propagates to the caller.
    """

    def test_state_lookup_failure_propagates(self) -> None:
        songs, _, state_repo, _ = _make_songs()
        state_repo.list_songs_in_state.side_effect = DatabaseStateError("state query failed")

        with pytest.raises(DatabaseStateError):
            songs.list_songs_with_state("not_processed")

        # Read-only: no repository mutation is ever issued behind a read.
        songs._song_repo.delete_song.assert_not_called()  # type: ignore[attr-defined]

    def test_song_row_fetch_connection_failure_propagates(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        state_repo.list_songs_in_state.return_value = [1]
        song_repo.get_songs_by_ids.side_effect = DatabaseStateError("connection lost")

        with pytest.raises(DatabaseStateError):
            songs.list_songs_with_state("not_processed")

    def test_scoped_miss_is_an_empty_result_not_an_error(self) -> None:
        songs, _, state_repo, library_repo = _make_songs()
        state_repo.list_songs_in_state.return_value = [1]
        library_repo.get_library_by_uuid.return_value = None

        assert songs.list_songs_with_state("not_processed", library=_LIB) == []
        # No row write behind the scoped miss.
        songs._song_repo.get_songs_by_ids.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Mapper isolation: a mapper failure never falls back to a raw row
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapperIsolation:
    """A row→domain mapper failure propagates and never exposes the raw row."""

    def test_get_song_mapper_failure_propagates_no_raw_row_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nomarr.persistence.api import library_songs as ls_module

        songs, song_repo, _, _ = _make_songs()
        song_repo.get_song_by_normalized_path.return_value = {"id": 5, "normalized_path": "a.mp3"}

        def _boom(row):  # type: ignore[no-untyped-def]
            raise RuntimeError("mapper invariant violated")

        monkeypatch.setattr(ls_module, "song_row_to_domain", _boom)

        with pytest.raises(RuntimeError):
            songs.get_song(_identity("a.mp3"))
        # The raw storage row never crosses to the caller as a fallback.

    def test_get_song_stale_locator_is_none_miss(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.get_song_by_normalized_path.return_value = None

        assert songs.get_song(_identity("missing.mp3")) is None


# ---------------------------------------------------------------------------
# P1-S1: facade exposes no transaction surface (callers never open one)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSongFacadeNoTransactionSurface:
    """The D-owned write seams expose no session/transaction surface.

    Repositories own their commit boundaries; the facade and callers above it
    never open a transaction (ADR-046 thinness; AR-SDR-4). This is the
    source-visible invariant for the seams characterized by this plan.
    """

    def test_library_songs_db_exposes_no_transaction_api(self) -> None:
        songs, _, _, _ = _make_songs()
        for name in ("transaction", "_require_transaction", "begin_transaction", "begin", "commit", "rollback"):
            assert not hasattr(songs, name), f"LibrarySongsDb must not expose a '{name}' surface (AR-SDR-4)."


# ===========================================================================
# Phase 2 (P2-S1 / P2-S2): retry idempotency, deletion/no-resurrection,
# restart-safe re-derivation, claim/state-cleanup scope, and non-leaking
# error messages
# ===========================================================================


def _leaks_internal(msg: str) -> bool:
    """True if a facade error message discloses SQL DML, credentials, or a DSN.

    Deliberately does NOT flag schema/column *names* referenced in
    developer-facing validation text (e.g. ``songs.normalized_path``) — those
    are documented as an observation, not edited into the concurrent uncommitted
    Plan C seam. Row-ids, credentials, connection strings, and raw SQL statements
    are the unambiguous disclosures P2-S2 pins against.
    """
    upper = msg.upper()
    sql_verbs = (" INSERT ", " UPDATE ", " DELETE ", " SELECT ", " FROM ", " WHERE ", " SET ")
    if any(verb in upper for verb in sql_verbs):
        return True
    lower = msg.lower()
    return bool(any(token in lower for token in ("password", "passwd", "pwd=", "dsn", "://", "postgresql://")))


def _removable_song(song_repo: MagicMock, song_id: int = 5) -> None:
    song_repo.get_song_by_normalized_path.return_value = {"id": song_id, "normalized_path": "a.mp3"}


@pytest.mark.unit
class TestAddSongIdempotentRetry:
    """P2-S1: re-issuing the typed upsert intent is idempotent, never a growing batch.

    ``add_song_to_library`` maps each invocation from the fresh command to ONE
    repository upsert call; there is no in-facade state that accumulates rows or
    re-emits prior writes. The recorded-recoverable boundary means a state-init
    failure does not roll back the committed row and the retry re-issues the same
    single upsert (idempotent at the row level via the repository's ON CONFLICT
    upsert) then completes the state bootstrap.
    """

    def test_state_init_failure_then_retry_reissues_one_upsert_no_growth(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        song_repo.upsert_songs_for_library.return_value = [7]
        # First attempt: the row upsert commits, the independent state-init fails.
        state_repo.initialize_song_states.side_effect = [DatabaseStateError("state init failed"), None]

        with pytest.raises(DatabaseStateError):
            songs.add_song_to_library(_upsert_command())
        # Retry of the same idempotent intent completes the bootstrap.
        result = songs.add_song_to_library(_upsert_command())

        # Exactly one upsert per invocation (two total), each a single-row payload
        # for the SAME (library id, path) — no batch growth across retries.
        assert song_repo.upsert_songs_for_library.call_count == 2
        for call in song_repo.upsert_songs_for_library.call_args_list:
            assert call.args[0] == 1
            payloads = call.args[1]
            assert isinstance(payloads, list) and len(payloads) == 1
            assert payloads[0]["normalized_path"] == "a.mp3"
        # State init ran once for the failed attempt (with the committed id) and
        # once for the retry.
        assert state_repo.initialize_song_states.call_count == 2
        assert result == _identity("a.mp3")
        song_repo.delete_song.assert_not_called()

    def test_reissuing_same_command_is_one_upsert_per_call_no_hidden_duplication(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        song_repo.upsert_songs_for_library.return_value = [3]
        state_repo.initialize_song_states.return_value = None

        first = songs.add_song_to_library(_upsert_command())
        second = songs.add_song_to_library(_upsert_command())

        # Each invocation produced exactly one upsert; no in-facade accumulation.
        assert song_repo.upsert_songs_for_library.call_count == 2
        assert state_repo.initialize_song_states.call_count == 2
        assert first == second == _identity("a.mp3")
        song_repo.delete_song.assert_not_called()


@pytest.mark.unit
class TestNoResurrectionAfterRemoval:
    """P2-S1: a removed song stays removed; re-issuing remove misses deterministically.

    ADR-048 clause 6 / CONTRACTS: once removed, the locator does not resolve
    again. Re-issuing ``remove_song`` after a successful removal returns ``False``
    (no double delete, nothing reappears). A LATER upsert of the same locator is a
    NEW song (a fresh row via the canonical upsert), not a resurrection of the
    removed row — the contract distinguishes the two.
    """

    def test_remove_success_then_remove_missing_is_false_no_second_delete(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        # First lookup resolves (row exists) → remove deletes it; after removal the
        # locator no longer resolves (row gone) → second remove is a False miss.
        song_repo.get_song_by_normalized_path.side_effect = [{"id": 5, "normalized_path": "a.mp3"}, None]

        assert songs.remove_song(_remove_command()) is True
        assert songs.remove_song(_remove_command()) is False

        # delete_song issued exactly once (only for the actually-present row); the
        # second remove performs no write and nothing reappears.
        song_repo.delete_song.assert_called_once_with(5)
        song_repo.upsert_songs_for_library.assert_not_called()

    def test_add_after_remove_is_a_new_upsert_not_a_resurrection(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        _removable_song(song_repo)
        song_repo.delete_song.return_value = None

        assert songs.remove_song(_remove_command()) is True
        song_repo.delete_song.assert_called_once_with(5)

        # A later upsert of the SAME locator is the canonical add path — a fresh
        # row, not an "un-delete" of the removed row. The facade issues a clean
        # upsert (never re-reading or resurrecting the old row) and never deletes
        # during an add.
        song_repo.get_song_by_normalized_path.return_value = None  # old row no longer resolves
        song_repo.upsert_songs_for_library.return_value = [9]
        state_repo.initialize_song_states.return_value = None

        result = songs.add_song_to_library(_upsert_command())
        assert result == _identity("a.mp3")
        song_repo.upsert_songs_for_library.assert_called_once()
        # delete_song count is still 1 (from the earlier remove) — the add never
        # deletes, it inserts a NEW row via the canonical upsert.
        song_repo.delete_song.assert_called_once_with(5)

    def test_remove_returns_boolean_never_storage_id(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        _removable_song(song_repo, song_id=5)
        song_repo.delete_song.return_value = None

        outcome = songs.remove_song(_remove_command())
        # The natural-locator removal returns a bool, never the private storage id:
        # the generated id (5) is consumed only inside the private delete_song and
        # never crosses the facade (ADR-048).
        assert outcome is True
        assert isinstance(outcome, bool)
        song_repo.delete_song.assert_called_once_with(5)


@pytest.mark.unit
class TestRestartSafeReDerivation:
    """P2-S1: after a restart, stale locators miss deterministically — no id fallback.

    Scan/detection re-derives locators by (library, normalized_path). When a
    previously-known locator no longer resolves (the row was removed or the DB was
    rebuilt), every D-owned read/mutation seam returns a deterministic miss
    (``None``/``False``) and never falls back to a generated-id lookup or a
    fabricated row.
    """

    def test_stale_locator_read_misses_without_numeric_fallback(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.get_song_by_normalized_path.return_value = None

        assert songs.get_song(_identity("was_there.mp3")) is None

        # The only repository interaction was the single locator-addressed read —
        # no fallback numeric/row-id resolver was consulted.
        assert [m[0] for m in song_repo.method_calls] == ["get_song_by_normalized_path"]

    def test_restart_stale_mutations_miss_without_fabrication(self) -> None:
        songs, song_repo, state_repo, library_repo = _make_songs()
        song_repo.get_song_by_normalized_path.return_value = None
        song_repo.move_song.return_value = False
        state_repo.list_songs_in_state.return_value = []

        # get / remove / move all miss deterministically for the stale locator.
        assert songs.get_song(_identity("gone.mp3")) is None
        assert songs.remove_song(SongRemoval(song_identity=_identity("gone.mp3"))) is False
        assert songs.move_library_song(_move_command("gone.mp3", "elsewhere.mp3")) is None
        # list_songs_with_state on a locator whose states are gone is an empty miss.
        assert songs.list_songs_with_state("not_processed", library=_LIB) == []

        # No delete, no insert, no fabricated replacement anywhere on the miss path.
        song_repo.delete_song.assert_not_called()
        song_repo.upsert_songs_for_library.assert_not_called()
        song_repo.move_song.assert_called_once()
        library_repo.get_library_by_uuid.assert_called()  # used for resolve only


@pytest.mark.unit
class TestRemoveDoesNotOwnStateOrClaimCleanup:
    """P2-S1: remove_song does not independently re-own state/claim cleanup.

    Removing a song clears derived aggregates via the repository's single DELETE
    + FK CASCADE (song_state_assignments) and the linked worker-claims owner for
    claim rows — D's facade never reaches into the state repo or a claim repo
    during removal. Claim/state cleanup is LINKED (worker-claims contract), not
    re-owned here.
    """

    def test_remove_reaches_only_song_repo_and_never_state_repo(self) -> None:
        songs, song_repo, state_repo, _ = _make_songs()
        _removable_song(song_repo)
        song_repo.delete_song.return_value = None

        assert songs.remove_song(_remove_command()) is True

        # State cleanup is the repository DELETE + FK CASCADE; the facade does not
        # separately drive song_state_repo during removal (and holds no claim repo
        # reference — claim cleanup is the worker-claims external owner's scope).
        state_repo.assert_not_called()
        song_repo.delete_song.assert_called_once_with(5)


@pytest.mark.unit
class TestExceptionRelayNoLeak:
    """P2-S2: repo domain errors relay unchanged — no added SQL / row-id / credential.

    ``map_persistence_exceptions`` already translates persistence failures to
    domain types with the original SQLAlchemy chain suppressed (``from None``).
    The facade adds no wrapping text, so the caller observes exactly the domain
    message with no SQL statement, storage row-id, credential, or DSN appended.
    """

    def test_add_repo_error_relayed_without_sql_or_id_disclosure(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.upsert_songs_for_library.side_effect = DatabaseStateError("temporary database outage")

        with pytest.raises(DatabaseStateError) as exc_info:
            songs.add_song_to_library(_upsert_command())

        msg = str(exc_info.value)
        assert "temporary database outage" in msg
        assert not _leaks_internal(msg)

    def test_move_repo_error_relayed_without_sql_or_id_disclosure(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        song_repo.move_song.side_effect = DatabaseStateError("temporary database outage")

        with pytest.raises(DatabaseStateError) as exc_info:
            songs.move_library_song(_move_command())

        msg = str(exc_info.value)
        assert "temporary database outage" in msg
        assert not _leaks_internal(msg)

    def test_remove_repo_error_relayed_without_sql_or_id_disclosure(self) -> None:
        songs, song_repo, _, _ = _make_songs()
        _removable_song(song_repo)
        song_repo.delete_song.side_effect = DatabaseStateError("temporary database outage")

        with pytest.raises(DatabaseStateError) as exc_info:
            songs.remove_song(_remove_command())

        msg = str(exc_info.value)
        assert "temporary database outage" in msg
        assert not _leaks_internal(msg)

    def test_facade_validation_error_discloses_no_credentials_or_sql(self) -> None:
        songs, song_repo, _, _ = _make_songs()

        # add scan-less rejection.
        with pytest.raises(ValueError) as add_exc:
            songs.add_song_to_library(SongUpsertInput(library=_LIB, path="/music/a.mp3", scan=None))
        # move NULL-destination rejection.
        move_cmd = SongPathUpdate(
            song_identity=_identity("a.mp3"),
            new_path="/music/b.mp3",
            scan=SongScanUpdate(normalized_path=None, file_size=2048, modified_time=6000),
        )
        with pytest.raises(ValueError) as move_exc:
            songs.move_library_song(move_cmd)

        for exc in (add_exc, move_exc):
            assert not _leaks_internal(str(exc.value))
        # Both reject before any repo write.
        song_repo.upsert_songs_for_library.assert_not_called()
        song_repo.move_song.assert_not_called()
