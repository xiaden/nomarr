"""Unit regressions for Issue #192 write-mode transition atomicity and serialization.

These tests drive the real ``PipelineRepository.change_write_mode`` intent through
a deterministic, stateful session double. They pin the invariants that the
endpoint previously violated:

- the write axis gate refuses a mode change while a tag write is admitted, with
  no mode update and no commit;
- the mode update and the ``tags_current`` → ``tags_not_fresh`` transition commit
  together, and a failure in either half commits nothing;
- after a failed attempt the persisted state is untouched, so a retry/restart
  starts from an unchanged, coherent state.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import LibraryOperationConflict
from nomarr.persistence.api.library_regions import LibraryRegionsDb
from nomarr.persistence.database.pipeline_repo import PipelineRepository

pytestmark = pytest.mark.unit

_LIBRARY = Library(
    name="library-a",
    root_path="/music/a",
    library_uuid="11111111-1111-1111-1111-111111111111",
)


class _Scalar:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return [SimpleNamespace(_mapping=row) for row in self._rows]


class _ReturningIds:
    def __init__(self, ids: list[int]) -> None:
        self._ids = ids

    def scalars(self) -> _ReturningIds:
        return self

    def all(self) -> list[int]:
        return list(self._ids)


class _NoResult:
    """Stand-in for a result whose rows the intent ignores."""


class _Store:
    """In-memory stand-in for the persisted library rows plus song-state assignments."""

    def __init__(
        self,
        *,
        mode: str = "full",
        tag_write_state: str = "not_written",
        current_songs: tuple[int, ...] = (7, 8),
    ) -> None:
        self.mode = mode
        self.assignments: dict[int, str] = dict.fromkeys(current_songs, "tags_current")
        self.pipeline_rows = [{"state_key": "tag_write_state", "state_data": {"state": tag_write_state}}]


class _ModeChangeSession:
    """Session double simulating one transaction of ``change_write_mode``.

    ``fail_on`` names a statement class ("mode" or "stale"); the matching
    statement raises before commit, so the buffered writes are discarded. A
    commit applies the buffered writes to the shared store.
    """

    def __init__(
        self,
        store: _Store,
        requested_mode: str,
        *,
        library_id: int = 17,
        fail_on: frozenset[str] = frozenset(),
    ) -> None:
        self._store = store
        self._requested_mode = requested_mode
        self._library_id = library_id
        self._fail_on = fail_on
        self.commits = 0
        self.statements: list[str] = []
        self._pending_stale: list[int] = []

    def begin_nested(self):
        return nullcontext()

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "DELETE FROM song_state_assignments" in sql:
            if "stale" in self._fail_on:
                raise RuntimeError("stale marking failed")
            stale = [song for song, state in self._store.assignments.items() if state == "tags_current"]
            self._pending_stale = stale
            return _ReturningIds(stale)
        if "UPDATE libraries" in sql:
            if "mode" in self._fail_on:
                raise RuntimeError("mode update failed")
            return _NoResult()
        if "INSERT INTO song_state_assignments" in sql:
            return _NoResult()
        if "song_states" in sql:
            return _Scalar(42)
        if "pipeline_states" in sql:
            return _Rows(self._store.pipeline_rows)
        if "libraries" in sql:
            return _Scalar(self._library_id)
        raise AssertionError(f"unexpected statement: {sql}")

    def commit(self) -> None:
        self.commits += 1
        self._store.mode = self._requested_mode
        for song in self._pending_stale:
            self._store.assignments[song] = "tags_not_fresh"


def _make_regions(
    store: _Store, *, fail_on: frozenset[str] = frozenset()
) -> tuple[LibraryRegionsDb, _ModeChangeSession]:
    session = _ModeChangeSession(store, "minimal", fail_on=fail_on)
    library_repo = MagicMock()
    library_repo.get_library_by_natural_key.return_value = {"id": 17}
    regions = LibraryRegionsDb(
        session=MagicMock(),
        library_repo=library_repo,
        song_state_repo=MagicMock(),
        pipeline_repo=PipelineRepository(session),
    )
    return regions, session


def test_change_write_mode_updates_mode_and_invalidates_in_one_commit() -> None:
    store = _Store()
    regions, session = _make_regions(store)

    affected = regions.change_write_mode(_LIBRARY, "minimal")

    assert affected == 2
    assert session.commits == 1
    assert store.mode == "minimal"
    assert set(store.assignments.values()) == {"tags_not_fresh"}
    mode_index = next(i for i, sql in enumerate(session.statements) if "UPDATE libraries" in sql)
    stale_index = next(i for i, sql in enumerate(session.statements) if "DELETE FROM song_state_assignments" in sql)
    assert mode_index < stale_index


def test_change_write_mode_conflicts_while_tag_write_admitted() -> None:
    store = _Store(tag_write_state="writing")
    regions, session = _make_regions(store)

    with pytest.raises(LibraryOperationConflict) as exc_info:
        regions.change_write_mode(_LIBRARY, "minimal")

    conflict = exc_info.value
    assert conflict.operation == "write_mode"
    assert conflict.tag_write_state == "writing"
    assert session.commits == 0
    assert store.mode == "full"
    assert set(store.assignments.values()) == {"tags_current"}
    assert not any(
        "UPDATE libraries" in sql or "DELETE FROM song_state_assignments" in sql for sql in session.statements
    )


def test_change_write_mode_failure_during_stale_marking_commits_nothing() -> None:
    store = _Store()
    regions, session = _make_regions(store, fail_on=frozenset({"stale"}))

    with pytest.raises(RuntimeError, match="stale marking failed"):
        regions.change_write_mode(_LIBRARY, "minimal")

    assert session.commits == 0
    # The mode update was issued but discarded with the failed transaction.
    assert any("UPDATE libraries" in sql for sql in session.statements)
    assert store.mode == "full"
    assert set(store.assignments.values()) == {"tags_current"}


def test_change_write_mode_failure_during_mode_update_commits_nothing() -> None:
    store = _Store()
    regions, session = _make_regions(store, fail_on=frozenset({"mode"}))

    with pytest.raises(RuntimeError, match="mode update failed"):
        regions.change_write_mode(_LIBRARY, "minimal")

    assert session.commits == 0
    assert store.mode == "full"
    assert set(store.assignments.values()) == {"tags_current"}


def test_change_write_mode_retry_after_failure_succeeds_from_coherent_state() -> None:
    store = _Store()
    failed_regions, failed_session = _make_regions(store, fail_on=frozenset({"stale"}))

    with pytest.raises(RuntimeError):
        failed_regions.change_write_mode(_LIBRARY, "minimal")

    assert failed_session.commits == 0

    # Retry/restart: a fresh unit of work sees the unchanged persisted state.
    retry_regions, retry_session = _make_regions(store)

    affected = retry_regions.change_write_mode(_LIBRARY, "minimal")

    assert affected == 2
    assert retry_session.commits == 1
    assert store.mode == "minimal"
    assert set(store.assignments.values()) == {"tags_not_fresh"}


def test_change_write_mode_with_no_current_songs_still_commits_mode() -> None:
    store = _Store(current_songs=())
    regions, session = _make_regions(store)

    affected = regions.change_write_mode(_LIBRARY, "minimal")

    assert affected == 0
    assert session.commits == 1
    assert store.mode == "minimal"
