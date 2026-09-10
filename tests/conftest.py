"""Root-level conftest for pytest fixtures.

Provides repo-wide contract fixtures for the typed song state-read result (Plan E P2-S3).

Plan C pins the *implementation* semantics of ``LibrarySongsDb.list_songs_with_state`` in
``tests/unit/persistence/api/test_library_db.py`` (typed ``SongStateCandidate`` return shape,
default ordering, ``order_by_activity`` + ``limit``, library-scope ownership filtering,
deterministic ``[]`` on empty/unknown-library) and in ``test_song_failure_safety.py``
(read-only no-write behind the read, ``DatabaseStateError`` propagation, scoped-miss-is-empty).
Those are not importable, so F/H/K *caller-migration* tests (which mock the facade and consume
typed results in their own component tests) have no shared way to build a ``SongStateCandidate``
and assert the semantic-invariant contract.

This root conftest (an ancestor of every ``tests/unit/**`` F/H/K test directory) exposes that
thin, reusable, non-duplicative surface as factory fixtures available repo-wide:

- ``song_state_contract`` — a namespace of the builder/checker helpers (``make_candidate``,
  ``make_song``, ``make_library``, ``assert_candidate_semantic``) plus the canonical named
  exceptions (``DuplicateEntityError``, ``DatabaseStateError``).
- ``make_song_state_candidate`` — a single factory fixture returning just ``make_candidate``.

A caller-migration test consumes them by requesting the fixture:

    def test_consumer(song_state_contract):          # or: def test_consumer(make_song_state_candidate)
        candidate = song_state_contract.make_candidate("music/a.flac", states=("processed",))
        song_state_contract.assert_candidate_semantic(candidate)

This is a test-support builder only — it does **not** ratify or amend the candidate shape
(Plan J owns that ratification); it constructs the already-shipped dataclass
``SongStateCandidate``. The named-exceptions contract is pinned in the C/D facade tests; the
two exception types are surfaced here so caller tests that mock the facade raise the canonical
types without importing them ad hoc.

Note: fixtures previously defined here (good_library_root, bad_library_root,
good_library_paths) were removed earlier as they were unused by any test.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.exceptions import DatabaseStateError, DuplicateEntityError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    MakeCandidate = Callable[..., SongStateCandidate]


def _make_library(name: str = "Music", root_path: str = "/music") -> LibraryIdentity:
    """Return a ``LibraryIdentity`` for a canonical test library."""
    return LibraryIdentity(name=name, root_path=root_path)


def _make_song(
    normalized_path: str = "music/a.flac",
    *,
    path: str | None = None,
    library: LibraryIdentity | None = None,
    **overrides: object,
) -> Song:
    """Build a minimal semantic domain ``Song`` (mirrors the caller-migration test convention).

    ``path`` defaults to the owning library's ``root_path`` joined with ``normalized_path``.
    """
    lib = library or _make_library()
    base = {
        "path": path or f"{lib.root_path.rstrip('/')}/{normalized_path.lstrip('/')}",
        "normalized_path": normalized_path,
        "file_size": 0,
        "modified_time": 0,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": True,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 0,
    }
    base.update(overrides)
    return Song(**base)  # type: ignore[arg-type]


def _make_candidate(
    normalized_path: str = "music/a.flac",
    *,
    library: LibraryIdentity | None = None,
    path: str | None = None,
    states: Iterable[str] = ("hydrated", "processed"),
) -> SongStateCandidate:
    """Build a typed ``SongStateCandidate`` consistent with CONTRACTS §5.

    Produces a candidate whose ``identity`` (locator) and ``song`` agree on
    ``normalized_path`` and whose ``states`` is a sorted, unique tuple of state *names*.
    """
    lib = library or _make_library()
    song = _make_song(normalized_path, path=path, library=lib)
    return SongStateCandidate(
        identity=SongIdentity(library=lib, normalized_path=song.normalized_path),
        song=song,
        states=tuple(sorted(set(states))),
    )


def _assert_candidate_semantic(candidate: SongStateCandidate) -> None:
    """Assert a typed state-read candidate obeys the semantic-invariant contract.

    Fails (``AssertionError``) if the candidate (or its ``song``/``identity``) carries a
    generated ``songs.id``/``library_id``, if ``song`` is a raw row/dict shape, or if the
    locator and song disagree on ``normalized_path`` (ADR-047/048; CONTRACTS §3/§5).
    """
    assert isinstance(candidate, SongStateCandidate), "state-read result must be SongStateCandidate"
    identity = candidate.identity
    song = candidate.song
    assert isinstance(identity, SongIdentity), "candidate.identity must be a SongIdentity locator"
    assert isinstance(song, Song), "candidate.song must be a semantic Song, never a raw row/dict"
    assert not hasattr(song, "song_id"), "semantic Song must not carry generated songs.id"
    assert not hasattr(song, "library_id"), "semantic Song must not carry integer library_id"
    assert not hasattr(identity, "song_id"), "SongIdentity locator must not carry generated songs.id"
    assert isinstance(identity.library, LibraryIdentity), "locator must carry a LibraryIdentity"
    assert identity.normalized_path == song.normalized_path, "locator and Song must agree on normalized_path"
    assert isinstance(candidate.states, tuple)
    assert all(isinstance(s, str) for s in candidate.states), "states must be state names, never ids"
    assert candidate.states == tuple(sorted(set(candidate.states))), "states must be sorted and unique"


@pytest.fixture(scope="session")
def song_state_contract() -> SimpleNamespace:
    """Repo-wide helper namespace for building/asserting typed song state-read results.

    Available to every ``tests/**`` F/H/K caller-migration test via fixture injection.
    Exposes ``make_candidate``, ``make_song``, ``make_library``, ``assert_candidate_semantic``,
    and the canonical named exceptions ``DuplicateEntityError``/``DatabaseStateError``.
    """
    return SimpleNamespace(
        make_candidate=_make_candidate,
        make_song=_make_song,
        make_library=_make_library,
        assert_candidate_semantic=_assert_candidate_semantic,
        DuplicateEntityError=DuplicateEntityError,
        DatabaseStateError=DatabaseStateError,
    )


@pytest.fixture(scope="session")
def make_song_state_candidate() -> Callable[..., SongStateCandidate]:
    """Factory fixture returning the ``make_candidate`` builder for a typed state-read result."""
    return _make_candidate
