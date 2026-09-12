"""D2 owner-behavior tests for the mood tag persistence facade.

These tests are fault-injection/unit/static evidence.  They exercise the real
``LibraryTagsDb`` control flow with a fake session/repository boundary so that
validation ordering, duplicate policy, missing-locator typing, retry/fresh-session
disposal, ambiguous-commit handling, redaction, and same-locator serialization are
pinned without a live PostgreSQL server.  Live PostgreSQL mutation evidence is
owned by D3/D2R-B/CI and is deliberately not claimed here.

Same-locator single-winner invariant (D2R-A): the owner locks every resolved
private ``songs`` row with ``SELECT ... FOR NO KEY UPDATE`` in ascending private-id
order before any mood/marker read, so a later replacement for the same
``SongIdentity`` reads state after the predecessor commits (no interleave, no
union); batch lock order is all-or-none.  ``TestMoodSameLocatorSerialization``
pins the lock statement and its ordering; real-PostgreSQL single-winner evidence
is owned by D2R-B, not by this fake-session module.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodAssignments,
    MoodBatchResult,
    MoodReplacementCommand,
    MoodWriteResult,
)
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.database.song_tag_repo import _MOOD_TAG_NAMES, SongTagRepository

LIBRARY_UUID = "de131b32-af5c-5a84-8874-58e3dc0e2dcd"
SONG = SongIdentity(LibraryIdentity(LIBRARY_UUID), "a.mp3")
MARKER = CalibrationMoodMarker.calibrated("a" * 32)
UNCALIBRATED = CalibrationMoodMarker.uncalibrated()
MOOD_TAGS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Minimal repository-owned session double.

    Selects consume programmed results in order (edges first, then markers);
    mutations are recorded.  ``fail_select_numbers`` injects an exception at a
    1-based select position to emulate a poisoned/retryable session.
    """

    def __init__(
        self,
        select_results: list[list[tuple[Any, ...]]] | None = None,
        fail_select_numbers: dict[int, BaseException] | None = None,
        fail_lock_numbers: dict[int, BaseException] | None = None,
        fail_commit: BaseException | None = None,
    ) -> None:
        self.select_results = list(select_results or [])
        self.fail_select_numbers = dict(fail_select_numbers or {})
        self.fail_lock_numbers = dict(fail_lock_numbers or {})
        self.fail_commit = fail_commit
        self.mutations: list[Any] = []
        self.selects: list[Any] = []
        #: Same-locator serialization locks (``SELECT ... FOR UPDATE``), kept
        #: separate from the mood/marker reads so their order is observable.
        self.locks: list[Any] = []
        #: Unified call order across locks, reads, and mutations.
        self.call_order: list[str] = []
        self.commits = 0
        self.commit_attempts = 0
        self.rollbacks = 0
        self.removes = 0
        self._select_index = 0
        self._lock_index = 0

    def execute(self, statement: Any) -> _FakeResult:
        if isinstance(statement, Select):
            if getattr(statement, "_for_update_arg", None) is not None:
                self._lock_index += 1
                self.locks.append(statement)
                self.call_order.append("lock")
                injected = self.fail_lock_numbers.get(self._lock_index)
                if injected is not None:
                    raise injected
                return _FakeResult([])
            self._select_index += 1
            self.selects.append(statement)
            self.call_order.append("select")
            injected = self.fail_select_numbers.get(self._select_index)
            if injected is not None:
                raise injected
            rows = self.select_results.pop(0) if self.select_results else []
            return _FakeResult(rows)
        self.mutations.append(statement)
        self.call_order.append("mutation")
        return _FakeResult([])

    def commit(self) -> None:
        self.commit_attempts += 1
        if self.fail_commit is not None:
            raise self.fail_commit
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def remove(self) -> None:
        self.removes += 1


class _FakeTagRepo:
    def __init__(self, tag_ids: dict[tuple[str, str, str], int]) -> None:
        self._tag_ids = tag_ids

    def get_or_create_tags_batch(self, rows: list[dict[str, str]]) -> dict[tuple[str, str, str], int]:
        result: dict[tuple[str, str, str], int] = {}
        for row in rows:
            key = (row["namespace"], row["name"], row["value"])
            if key not in self._tag_ids:
                self._tag_ids[key] = 500 + len(self._tag_ids)
            result[key] = self._tag_ids[key]
        return result


class _FakeLibraryRepo:
    def __init__(self, uuid_map: dict[str, int]) -> None:
        self._map = uuid_map

    def get_library_ids_by_uuids(self, uuids: list[str]) -> dict[str, int]:
        return {uuid: self._map[uuid] for uuid in uuids if uuid in self._map}

    def get_library_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        return None


class _FakeSongRepo:
    def __init__(self, id_map: dict[tuple[int, str], int]) -> None:
        self._map = id_map

    def get_song_ids_by_normalized_paths(self, keys: list[tuple[int, str]]) -> dict[tuple[int, str], int]:
        return {key: self._map[key] for key in keys if key in self._map}


def _make_facade(
    *,
    select_results: list[list[tuple[Any, ...]]] | None = None,
    tag_ids: dict[tuple[str, str, str], int] | None = None,
    library_map: dict[str, int] | None = None,
    song_map: dict[tuple[int, str], int] | None = None,
    fail_select_numbers: dict[int, BaseException] | None = None,
    fail_lock_numbers: dict[int, BaseException] | None = None,
    fail_commit: BaseException | None = None,
) -> tuple[LibraryTagsDb, _FakeSession]:
    session = _FakeSession(
        select_results=select_results,
        fail_select_numbers=fail_select_numbers,
        fail_lock_numbers=fail_lock_numbers,
        fail_commit=fail_commit,
    )
    tag_repo = _FakeTagRepo({} if tag_ids is None else tag_ids)
    song_repo = _FakeSongRepo({(1, "a.mp3"): 7} if song_map is None else song_map)
    library_repo = _FakeLibraryRepo({LIBRARY_UUID: 1} if library_map is None else library_map)
    # The Tier-2 song-tag repository is the real mood owner; the facade only
    # validates and delegates. Wiring the real owner through the fake session
    # exercises the relocated SQL/transaction/retry path through the public API.
    song_tag_repo = SongTagRepository(
        session=cast("Any", session),
        tag_repo=cast("Any", tag_repo),
        song_repo=cast("Any", song_repo),
        library_repo=cast("Any", library_repo),
    )
    facade = LibraryTagsDb(
        session=cast("Any", session),
        tag_repo=cast("Any", tag_repo),
        song_tag_repo=song_tag_repo,
        song_repo=cast("Any", song_repo),
        library_repo=cast("Any", library_repo),
    )
    return facade, session


def _command(
    assignments: MoodAssignments | None,
    marker: CalibrationMoodMarker = UNCALIBRATED,
    song: SongIdentity = SONG,
) -> MoodReplacementCommand:
    return MoodReplacementCommand(song=song, assignments=assignments, marker=marker)


def _compiled(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _tag_ids_for(*identities: tuple[str, str]) -> dict[tuple[str, str, str], int]:
    return {("nom", name, value): 100 + index for index, (name, value) in enumerate(identities)}


@pytest.mark.unit
class TestMoodBatchValidation:
    def test_conflicting_duplicate_locator_rejected_before_sql(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade, session = _make_facade()
        monkeypatch.setattr(
            facade._song_tag_repo,
            "replace_mood_tags_batch",
            lambda _commands: pytest.fail("SQL must not run for conflicting duplicates"),
        )
        result = facade.replace_mood_tags_batch(
            (
                _command(MoodAssignments(strict=("happy",))),
                _command(MoodAssignments(strict=("sad",))),
            )
        )
        assert result.status == "INVALID_VALUE"
        assert result.command_count == 0
        assert session.mutations == []
        assert session.commits == 0

    def test_identical_duplicate_locator_folds_to_one_command(self) -> None:
        normalized = LibraryTagsDb._normalize_mood_commands(
            (
                _command(MoodAssignments(strict=("happy",))),
                _command(MoodAssignments(strict=("happy",))),
            )
        )
        assert len(normalized) == 1

    def test_batch_over_max_rejected_before_sql(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade, session = _make_facade()
        monkeypatch.setattr(
            facade._song_tag_repo,
            "replace_mood_tags_batch",
            lambda _commands: pytest.fail("SQL must not run for an over-bound batch"),
        )
        commands = tuple(_command(MoodAssignments(strict=(f"v{index}",))) for index in range(1001))
        result = facade.replace_mood_tags_batch(commands)
        assert result.status == "INVALID_VALUE"
        assert session.mutations == []
        assert session.commits == 0

    def test_non_sequence_and_non_command_are_invalid(self) -> None:
        facade, session = _make_facade()
        assert facade.replace_mood_tags_batch(cast("Any", iter(()))).status == "INVALID_VALUE"
        assert facade.replace_mood_tags_batch(cast("Any", ("not-a-command",))).status == "INVALID_VALUE"
        assert session.mutations == []

    def test_empty_batch_is_deterministic_no_op(self) -> None:
        facade, session = _make_facade()
        assert facade.replace_mood_tags_batch(()) == MoodBatchResult("UNCHANGED")
        assert session.mutations == []
        assert session.commits == 0
        assert session.rollbacks == 0


@pytest.mark.unit
class TestMoodReplacementSemantics:
    def test_normal_replacement_inserts_all_tiers_in_one_transaction(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            tag_ids=_tag_ids_for(("nom:mood-strict", "happy"), ("nom:mood-regular", "calm")),
        )
        result = facade.replace_mood_tags_batch(
            (_command(MoodAssignments(strict=("happy",), regular=("calm",)), marker=MARKER),)
        )
        assert result == MoodBatchResult("UPDATED", command_count=1, changed_count=1)
        assert session.commits == 1
        assert len(session.mutations) == 2
        edge_insert, marker_insert = session.mutations
        edge_compiled = edge_insert.compile(dialect=postgresql.dialect())
        marker_compiled = marker_insert.compile(dialect=postgresql.dialect())
        assert "INSERT INTO song_tags" in str(edge_compiled)
        assert "INSERT INTO song_mood_calibration_markers" in str(marker_compiled)
        assert "ON CONFLICT" in str(marker_compiled)
        # Both resolved mood tag ids are bound into the single song_tags insert.
        assert {100, 101}.issubset(set(edge_compiled.params.values()))
        assert {1.0}.issubset(set(edge_compiled.params.values()))
        assert "nomarr" in edge_compiled.params.values()

    def test_absent_and_none_tiers_clear_existing_moods(self) -> None:
        existing = [
            (7, "nom:mood-strict", "happy", 11),
            (7, "nom:mood-regular", "calm", 12),
        ]
        facade, session = _make_facade(select_results=[existing, [(7, "a" * 32)]])
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result == MoodBatchResult("UPDATED", command_count=1, changed_count=1)
        assert session.commits == 1
        assert len(session.mutations) == 2
        edge_delete, marker_delete = session.mutations
        assert "DELETE FROM song_tags" in _compiled(edge_delete)
        assert "DELETE FROM song_mood_calibration_markers" in _compiled(marker_delete)

    def test_unchanged_edges_and_metadata_are_preserved_byte_for_byte(self) -> None:
        # Same identity already exists: the owner must not delete/reinsert it, so
        # stored confidence/source/created_at are untouched.
        existing = [(7, "nom:mood-strict", "happy", 11)]
        facade, session = _make_facade(select_results=[existing, []])
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",))),))
        assert result == MoodBatchResult("UNCHANGED", command_count=1, changed_count=0)
        assert session.mutations == []
        assert session.commits == 1

    def test_tier_replacement_only_touches_mood_edges(self) -> None:
        existing = [(7, "nom:mood-strict", "happy", 11)]
        facade, session = _make_facade(
            select_results=[existing, []],
            tag_ids=_tag_ids_for(("nom:mood-regular", "calm")),
        )
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(regular=("calm",))),))
        assert result == MoodBatchResult("UPDATED", command_count=1, changed_count=1)
        edge_delete, edge_insert = session.mutations
        assert "DELETE FROM song_tags" in _compiled(edge_delete)
        assert "INSERT INTO song_tags" in _compiled(edge_insert)
        # Non-mood tag_namespaces/names are never in the delete predicate scope.
        assert "default" not in _compiled(edge_delete)

    def test_marker_only_change_commits(self) -> None:
        existing = [(7, "nom:mood-strict", "happy", 11)]
        facade, session = _make_facade(select_results=[existing, []])
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",)), marker=MARKER),))
        assert result == MoodBatchResult("UPDATED", command_count=1, changed_count=1)
        assert len(session.mutations) == 1
        assert "INSERT INTO song_mood_calibration_markers" in _compiled(session.mutations[0])


@pytest.mark.unit
class TestMoodLocatorAndFailure:
    def test_stale_locator_is_typed_missing_without_mutation(self) -> None:
        facade, session = _make_facade(library_map={})
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",))),))
        assert result == MoodBatchResult("MISSING_LOCATOR", command_count=1, changed_count=0)
        assert session.mutations == []
        assert session.commits == 0
        assert session.rollbacks == 1

    def test_infrastructure_failure_is_never_a_locator_miss(self) -> None:
        facade, _session = _make_facade(
            fail_select_numbers={1: RuntimeError("connection reset")},
        )
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "INFRA_FAILURE"
        assert result.status != "MISSING_LOCATOR"

    def test_injected_fault_rolls_back_and_disposes_session(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            fail_select_numbers={2: RuntimeError("fault after first select")},
        )
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "INFRA_FAILURE"
        assert session.rollbacks == 1
        assert session.removes == 1
        assert session.commits == 0


@pytest.mark.unit
class TestMoodRetryAndAmbiguity:
    @staticmethod
    def _operational(pgcode: str) -> OperationalError:
        return OperationalError("SELECT 1", {}, type("_PgError", (Exception,), {"pgcode": pgcode})())

    def _single_command_facade(self, failure: BaseException) -> tuple[LibraryTagsDb, _FakeSession]:
        return _make_facade(
            select_results=[[], []],
            fail_select_numbers={1: failure},
        )

    def test_retryable_sqlstate_retries_in_fresh_session(self) -> None:
        facade, session = self._single_command_facade(self._operational("40001"))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "UNCHANGED"
        assert session.commits == 1
        assert session.removes == 1
        assert session.rollbacks == 1

    def test_deadlock_and_lock_not_available_are_retryable(self) -> None:
        for pgcode in ("40P01", "55P03"):
            facade, session = self._single_command_facade(self._operational(pgcode))
            assert facade.replace_mood_tags_batch((_command(None),)).status == "UNCHANGED"
            assert session.commits == 1

    def test_retry_is_bounded_and_then_infra_failure(self) -> None:
        facade, session = _make_facade(
            fail_select_numbers={position: self._operational("40001") for position in range(1, 101)},
        )
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "INFRA_FAILURE"
        assert session.commits == 0
        assert session.removes == 3

    def test_ambiguous_commit_does_not_retry_or_claim_success(self) -> None:
        facade, session = self._single_command_facade(self._operational("40003"))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "AMBIGUOUS_COMMIT"
        assert session.commits == 0
        assert session.removes == 1


@pytest.mark.unit
class TestMoodRedactionAndForbiddenPaths:
    def test_public_results_expose_only_status_and_counts(self) -> None:
        facade, _session = _make_facade(select_results=[[], []], tag_ids=_tag_ids_for(("nom:mood-strict", "happy")))
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",))),))
        rendered = f"{result!r} {result.status} {result.command_count} {result.changed_count}"
        for secret in ("happy", "a.mp3", LIBRARY_UUID, "nom:mood", "song_id", "password"):
            assert secret not in rendered

    def test_single_delegates_to_batch_and_maps_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade, _session = _make_facade()
        monkeypatch.setattr(
            facade,
            "replace_mood_tags_batch",
            lambda commands: MoodBatchResult("UPDATED", command_count=len(commands), changed_count=1),
        )
        result = facade.replace_mood_tags(SONG, MoodAssignments(strict=("a",), regular=("b",)), UNCALIBRATED)
        assert result == MoodWriteResult("UPDATED", assignment_count=2)

    def test_missing_locator_single_reports_zero_assignments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade, _session = _make_facade()
        monkeypatch.setattr(
            facade,
            "replace_mood_tags_batch",
            lambda commands: MoodBatchResult("MISSING_LOCATOR", command_count=len(commands)),
        )
        result = facade.replace_mood_tags(SONG, MoodAssignments(strict=("a",)), UNCALIBRATED)
        assert result == MoodWriteResult("MISSING_LOCATOR", assignment_count=0)

    def test_mood_owner_does_not_use_generic_or_caller_paths(self) -> None:
        # Tier-3 facade: validation + delegation only, never generic/caller paths.
        facade_source = inspect.getsource(LibraryTagsDb.replace_mood_tags) + inspect.getsource(
            LibraryTagsDb.replace_mood_tags_batch
        )
        assert "replace_song_tags" not in facade_source
        assert "save_mood_tags" not in facade_source
        assert "_session.begin" not in facade_source
        assert "text(" not in facade_source
        # The Tier-2 owner never composes the generic/caller paths either.
        owner = inspect.getsource(SongTagRepository._replace_mood_batch_once)
        assert "replace_song_tags" not in owner
        assert "save_mood_tags" not in owner
        assert "_session.begin" not in owner
        assert "text(" not in owner
        # The batch owner never loops over the public single-command path.
        assert "replace_mood_tags(" not in inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)

    def test_public_signatures_are_domain_only(self) -> None:
        single = inspect.signature(LibraryTagsDb.replace_mood_tags)
        batch = inspect.signature(LibraryTagsDb.replace_mood_tags_batch)
        assert tuple(single.parameters) == ("self", "song", "assignments", "marker")
        assert tuple(batch.parameters) == ("self", "commands")
        assert "song_id" not in single.parameters
        assert "song_id" not in batch.parameters

    def test_only_three_literal_mood_tiers_are_owned(self) -> None:
        assert _MOOD_TAG_NAMES == ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
        assert MOOD_TAGS == _MOOD_TAG_NAMES


def _dbapi_error(cls: type[Any], pgcode: str | None = None) -> BaseException:
    """Build a SQLAlchemy DBAPI error whose ``orig`` carries (or omits) a pgcode."""
    attrs = {"pgcode": pgcode} if pgcode is not None else {}
    return cls("STMT", {}, type("_PgError", (Exception,), attrs)())


@pytest.mark.unit
class TestMoodBatchAllOrNoneAndBounds:
    def test_multi_command_all_or_none_rolls_back_all_members(self) -> None:
        song_b = SongIdentity(LibraryIdentity(LIBRARY_UUID), "b.mp3")
        facade, session = _make_facade(
            select_results=[[], []],
            fail_select_numbers={2: RuntimeError("fault before marker read")},
            song_map={(1, "a.mp3"): 7, (1, "b.mp3"): 8},
        )
        result = facade.replace_mood_tags_batch(
            (
                _command(MoodAssignments(strict=("happy",)), song=SONG),
                _command(MoodAssignments(strict=("sad",)), song=song_b),
            )
        )
        assert result.status == "INFRA_FAILURE"
        assert result.command_count == 2
        assert session.commits == 0
        assert session.mutations == []
        assert session.rollbacks == 1
        assert session.removes == 1

    def test_partial_batch_stale_locator_returns_typed_miss(self) -> None:
        song_b = SongIdentity(LibraryIdentity(LIBRARY_UUID), "missing.mp3")
        facade, session = _make_facade(
            select_results=[[], []],
            song_map={(1, "a.mp3"): 7},
        )
        result = facade.replace_mood_tags_batch(
            (
                _command(MoodAssignments(strict=("happy",)), song=SONG),
                _command(MoodAssignments(strict=("sad",)), song=song_b),
            )
        )
        assert result == MoodBatchResult("MISSING_LOCATOR", command_count=2, changed_count=0)
        assert session.commits == 0
        assert session.mutations == []
        assert session.rollbacks == 1

    def test_duplicate_locator_differing_only_by_marker_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade, session = _make_facade()
        monkeypatch.setattr(
            facade._song_tag_repo,
            "replace_mood_tags_batch",
            lambda _commands: pytest.fail("SQL must not run for a marker-conflicting duplicate"),
        )
        result = facade.replace_mood_tags_batch(
            (
                _command(MoodAssignments(strict=("happy",)), MARKER),
                _command(MoodAssignments(strict=("happy",)), UNCALIBRATED),
            )
        )
        assert result.status == "INVALID_VALUE"
        assert session.mutations == []

    def test_exact_1000_commands_accepted(self) -> None:
        commands: list[MoodReplacementCommand] = []
        song_map: dict[tuple[int, str], int] = {}
        for index in range(1000):
            path = f"s{index}.mp3"
            song_map[(1, path)] = 1000 + index
            commands.append(_command(None, song=SongIdentity(LibraryIdentity(LIBRARY_UUID), path)))
        facade, session = _make_facade(select_results=[[], []], song_map=song_map)
        assert len(LibraryTagsDb._normalize_mood_commands(tuple(commands))) == 1000
        result = facade.replace_mood_tags_batch(tuple(commands))
        assert result.status == "UNCHANGED"
        assert result.command_count == 1000
        assert session.commits == 1

    def test_duplicate_edge_23505_is_infra_not_silent(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            fail_select_numbers={1: _dbapi_error(IntegrityError, "23505")},
        )
        result = facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",))),))
        assert result.status == "INFRA_FAILURE"
        assert session.commits == 0
        assert session.removes == 1


@pytest.mark.unit
class TestMoodPreservationAndBackfill:
    def test_uncalibrated_missing_marker_does_not_backfill(self) -> None:
        facade, session = _make_facade(select_results=[[], []])
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result == MoodBatchResult("UNCHANGED", command_count=1, changed_count=0)
        assert session.mutations == []
        assert session.commits == 1
        # No inference/backfill from the applicability state column, in facade or owner.
        assert "calibration_hash" not in inspect.getsource(LibraryTagsDb)
        assert "calibration_hash" not in inspect.getsource(SongTagRepository._replace_mood_batch_once)

    def test_edge_select_is_scoped_to_nom_mood_tiers(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            tag_ids=_tag_ids_for(("nom:mood-strict", "happy")),
        )
        facade.replace_mood_tags_batch((_command(MoodAssignments(strict=("happy",))),))
        assert session.selects, "the owner must issue its set-based edge read"
        compiled = session.selects[0].compile(dialect=postgresql.dialect())
        string_params: set[str] = set()
        for value in compiled.params.values():
            if isinstance(value, str):
                string_params.add(value)
            elif isinstance(value, (list, tuple, set)):
                string_params.update(item for item in value if isinstance(item, str))
        assert "nom" in string_params
        assert set(_MOOD_TAG_NAMES).issubset(string_params)

    def test_changed_edges_never_rewrite_unrelated_metadata(self) -> None:
        existing = [(7, "nom:mood-strict", "happy", 11)]
        facade, session = _make_facade(select_results=[existing, []])
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "UPDATED"
        assert len(session.mutations) == 1
        compiled = _compiled(session.mutations[0])
        assert "DELETE FROM song_tags" in compiled
        assert "UPDATE" not in compiled


@pytest.mark.unit
class TestMoodCommitPhase:
    def _facade_with_commit_failure(self, exc: BaseException) -> tuple[LibraryTagsDb, _FakeSession]:
        return _make_facade(select_results=[[], []], fail_commit=exc)

    def test_pgcode_less_commit_operational_error_is_ambiguous(self) -> None:
        facade, session = self._facade_with_commit_failure(_dbapi_error(OperationalError))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "AMBIGUOUS_COMMIT"
        assert session.commit_attempts == 1
        assert session.commits == 0
        assert session.rollbacks == 1
        assert session.removes == 1

    @pytest.mark.parametrize("exc_cls", [InterfaceError, DBAPIError])
    def test_pgcode_less_commit_variants_are_ambiguous(self, exc_cls: type[Any]) -> None:
        facade, session = self._facade_with_commit_failure(_dbapi_error(exc_cls))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "AMBIGUOUS_COMMIT"
        assert session.commit_attempts == 1
        assert session.commits == 0

    def test_commit_40003_is_ambiguous_without_retry(self) -> None:
        facade, session = self._facade_with_commit_failure(_dbapi_error(OperationalError, "40003"))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "AMBIGUOUS_COMMIT"
        assert session.commit_attempts == 1
        assert session.removes == 1

    def test_commit_retryable_sqlstate_is_bounded_fresh_session_retry(self) -> None:
        facade, session = self._facade_with_commit_failure(_dbapi_error(OperationalError, "40001"))
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "INFRA_FAILURE"
        assert session.commit_attempts == 3
        assert session.commits == 0
        assert session.removes == 3

    def test_pgcode_less_pre_commit_stays_infra_failure(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            fail_select_numbers={1: _dbapi_error(OperationalError)},
        )
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "INFRA_FAILURE"
        assert result.status != "AMBIGUOUS_COMMIT"
        assert session.commits == 0

    def test_single_unmocked_maps_assignment_count(self) -> None:
        facade, session = _make_facade(
            select_results=[[], []],
            tag_ids=_tag_ids_for(("nom:mood-strict", "a"), ("nom:mood-regular", "b")),
        )
        result = facade.replace_mood_tags(SONG, MoodAssignments(strict=("a",), regular=("b",)), UNCALIBRATED)
        assert result == MoodWriteResult("UPDATED", assignment_count=2)
        assert session.commits == 1


@pytest.mark.unit
class TestMoodSameLocatorSerialization:
    """D2R-A same-locator single-winner serialization control flow.

    Invariant: the owner locks every resolved private ``songs`` row with
    ``SELECT ... FOR NO KEY UPDATE`` in ascending private-id order BEFORE any
    mood/marker read, so a later same-``SongIdentity`` replacement blocks until the predecessor
    commits and then reads committed state (no interleave, no union); a batch locks
    all rows all-or-none in one statement. These are fake-session proofs of the
    lock statement, its deterministic ordering, and its position relative to the
    mood read. Deterministic real-PostgreSQL single-winner evidence is owned by
    D2R-B, not by this module.
    """

    def test_lock_statement_targets_resolved_songs_row_for_update(self) -> None:
        facade, session = _make_facade(select_results=[[], []])
        facade.replace_mood_tags_batch((_command(None),))
        assert len(session.locks) == 1, "exactly one serialization lock per intent"
        compiled = session.locks[0].compile(dialect=postgresql.dialect())
        assert "FOR NO KEY UPDATE" in str(compiled)
        assert "FOR KEY SHARE" not in str(compiled)
        assert "songs" in str(compiled)
        assert "song_tags" not in str(compiled)
        assert next(iter(compiled.params.values())) == [7]

    def test_batch_lock_ids_are_deterministically_ascending(self) -> None:
        # Two distinct locators resolve to private ids 8 and 7 in that (supplied)
        # order; the batch must lock them as [7, 8] in ONE all-or-none statement.
        song_b = SongIdentity(LibraryIdentity(LIBRARY_UUID), "b.mp3")
        facade, session = _make_facade(
            select_results=[[], []],
            song_map={(1, "a.mp3"): 8, (1, "b.mp3"): 7},
        )
        facade.replace_mood_tags_batch((_command(None, song=SONG), _command(None, song=song_b)))
        assert len(session.locks) == 1, "a batch locks all rows in one all-or-none statement"
        compiled = session.locks[0].compile(dialect=postgresql.dialect())
        assert "FOR NO KEY UPDATE" in str(compiled)
        assert "ORDER BY songs.id" in str(compiled)
        assert next(iter(compiled.params.values())) == [7, 8]

    def test_lock_executes_before_the_mood_edge_read(self) -> None:
        facade, session = _make_facade(select_results=[[], []])
        facade.replace_mood_tags_batch((_command(None),))
        assert "lock" in session.call_order
        assert "select" in session.call_order
        assert session.call_order.index("lock") < session.call_order.index("select")

    def test_stale_locator_takes_no_lock(self) -> None:
        facade, session = _make_facade(library_map={})
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "MISSING_LOCATOR"
        assert session.locks == []
        assert session.mutations == []

    def test_retryable_lock_failure_uses_existing_fresh_session_retry(self) -> None:
        # A serialization/deadlock raised by the pre-commit lock is classified by
        # the existing retryable path (bounded fresh-session replay), never
        # reclassified through the commit phase.
        facade, session = _make_facade(
            select_results=[[], []],
            fail_lock_numbers={1: _dbapi_error(OperationalError, "40001")},
        )
        result = facade.replace_mood_tags_batch((_command(None),))
        assert result.status == "UNCHANGED"
        assert session.removes == 1
        assert session.commits == 1
        assert len(session.locks) == 2, "the retry must re-acquire the lock in the fresh session"
