"""Executable contract fixture tests (Plan E P2-S3).

Proves the repo-wide contract fixtures in ``tests/conftest.py`` (``song_state_contract`` /
``make_song_state_candidate``) build a contract-valid typed state-read result and that
``assert_candidate_semantic`` rejects a raw row/dict shape. This does NOT duplicate Plan C's
facade-mock coverage of ``list_songs_with_state`` (test_library_db.py / test_song_failure_safety.py);
it only makes the shared consumer-side contract executable for F/H/K caller-migration tests.

The named-exceptions contract (DuplicateEntityError / DatabaseStateError / ValueError-on-
invalid-command / deterministic None-[]-False misses) is already pinned in the C/D facade
tests; the two canonical types are surfaced on the fixture namespace for caller tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate

if TYPE_CHECKING:
    from types import SimpleNamespace


@pytest.mark.unit
def test_song_state_contract_make_candidate_builds_valid_result(song_state_contract: SimpleNamespace) -> None:
    candidate = song_state_contract.make_candidate("music/a.flac", states=("processed", "hydrated"))

    assert isinstance(candidate, SongStateCandidate)
    assert isinstance(candidate.song, Song)
    assert isinstance(candidate.identity, SongIdentity)
    assert candidate.states == ("hydrated", "processed")  # sorted, deduped by the fixture
    song_state_contract.assert_candidate_semantic(candidate)


@pytest.mark.unit
def test_make_song_state_candidate_factory_fixture(make_song_state_candidate) -> None:  # type: ignore[no-untyped-def]
    candidate = make_song_state_candidate("album/x.flac")
    assert isinstance(candidate, SongStateCandidate)
    assert candidate.identity.normalized_path == "album/x.flac"
    assert candidate.song.normalized_path == "album/x.flac"


@pytest.mark.unit
def test_candidate_locator_and_song_agree_and_carry_no_generated_id(
    song_state_contract: SimpleNamespace,
) -> None:
    library: LibraryIdentity = song_state_contract.make_library(name="LibA", root_path="/srv/music")
    candidate = song_state_contract.make_candidate("album/x.flac", library=library)

    assert candidate.identity.library == library
    assert candidate.identity.library.name == "LibA"
    assert candidate.identity.library.root_path == "/srv/music"
    assert candidate.song.normalized_path == "album/x.flac"
    assert candidate.song.path == "/srv/music/album/x.flac"
    # No generated key / storage identity on the semantic value or locator.
    assert not hasattr(candidate.song, "song_id")
    assert not hasattr(candidate.song, "library_id")
    assert not hasattr(candidate.identity, "song_id")


@pytest.mark.unit
def test_candidate_construction_rejects_raw_row_dict_song(song_state_contract: SimpleNamespace) -> None:
    """A raw storage-row/dict shape must never become a semantic candidate."""
    good = song_state_contract.make_candidate("a.flac")
    with pytest.raises(TypeError):
        SongStateCandidate(
            identity=good.identity,
            song={"id": 5, "path": "/music/a.flac", "normalized_path": "a.flac"},  # type: ignore[arg-type]
            states=good.states,
        )


@pytest.mark.unit
def test_assert_candidate_semantic_rejects_forced_raw_row_dict_song(song_state_contract: SimpleNamespace) -> None:
    """``assert_candidate_semantic`` still rejects a raw row/dict forced past construction."""
    bad = song_state_contract.make_candidate("a.flac")
    object.__setattr__(bad, "song", {"id": 5, "path": "/music/a.flac", "normalized_path": "a.flac"})
    with pytest.raises(AssertionError):
        song_state_contract.assert_candidate_semantic(bad)


@pytest.mark.unit
def test_named_exceptions_are_surfaced_for_caller_fault_tests(song_state_contract: SimpleNamespace) -> None:
    """Caller tests raising the canonical types via a facade mock get the real classes."""
    dup_err = song_state_contract.DuplicateEntityError
    state_err = song_state_contract.DatabaseStateError
    assert issubclass(dup_err, Exception)
    assert issubclass(state_err, Exception)
    assert dup_err is not state_err

    from unittest.mock import MagicMock

    db = MagicMock()
    db.library.list_songs_with_state.side_effect = state_err("connection lost")
    with pytest.raises(state_err):
        db.library.list_songs_with_state("processed")
