"""Tests for ``nomarr.components.library.move_detection_comp``.

Move detection is bounded and persistence-backed. ``detect_move_for_new_file``
computes the new file's chromaprint, asks persistence for the bounded,
library-scoped candidate set sharing that fingerprint, filters candidates (self,
same locator, duration tolerance, still-present source) and returns a
:class:`FileMove` only when exactly one absent survivor remains — zero or many
yields ``None``. ``relocate_song`` builds exactly one complete ``SongPathUpdate``
addressed by the source ``SongIdentity`` and reports whether it committed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.move_detection_comp import (
    FileMove,
    detect_move_for_new_file,
    relocate_song,
    song_identity_for,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
)
from nomarr.helpers.dataclasses.song_dataclass import ChromaprintSongMatches, Song

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_COMPONENT = "nomarr.components.library.move_detection_comp"


def make_db() -> MagicMock:
    """Build a mocked facade ``Database`` with sub-facades."""
    db = MagicMock()
    db.library = MagicMock()
    db.app = MagicMock()
    db.ml = MagicMock()
    return db


def _new_file_entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "path": "D:/Music/new/song.flac",
        "normalized_path": "new/song.flac",
        "file_size": 1000,
        "modified_time": 2000,
        "duration_seconds": 180.0,
    }
    base.update(overrides)
    return base


def _song(
    path: str,
    normalized_path: str,
    duration_seconds: float | None = 180.0,
) -> Song:
    """Build the semantic ``Song`` a chromaprint candidate lookup returns."""
    return Song(
        path=path,
        normalized_path=normalized_path,
        file_size=1000,
        modified_time=2000,
        duration_seconds=duration_seconds,
        chromaprint="cp-candidate",
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=0,
    )


_LIBRARY = Library(library_uuid="45064f6d-d92e-5179-ad4d-6a15c1354737", name="main", root_path="/music")
_LIBRARY_IDENTITY = LibraryIdentity(
    library_uuid="45064f6d-d92e-5179-ad4d-6a15c1354737", name="main", root_path="/music"
)


@contextmanager
def _patched_detection(candidates: Sequence[Song]) -> Iterator[MagicMock]:
    """Patch chromaprint decode and the bounded DB candidate lookup."""
    with (
        patch(f"{_COMPONENT}.build_library_path_from_input") as mock_build,
        patch(f"{_COMPONENT}.compute_chromaprint_for_file") as mock_chromaprint,
        patch(f"{_COMPONENT}.find_move_candidates_by_chromaprint") as mock_candidate,
    ):
        mock_build.return_value.is_valid.return_value = True
        mock_chromaprint.return_value = "abc123"
        mock_candidate.return_value = ChromaprintSongMatches(songs=tuple(candidates), complete=True)
        yield mock_candidate


def _detect(
    entry: dict[str, object],
    candidates: Sequence[Song],
    *,
    source_present: bool = False,
) -> FileMove | None:
    with _patched_detection(candidates):
        return detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: source_present)


# ─────────────────────────────────────────────────────────────────────────
# song_identity_for
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_song_identity_for_builds_library_scoped_locator() -> None:
    identity = song_identity_for(_LIBRARY, "album/track.flac")
    assert identity == SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="album/track.flac")
    assert not hasattr(identity, "song_id")


@pytest.mark.unit
def test_song_identity_for_raises_when_library_uuid_missing() -> None:
    """A library without its immutable identity cannot address a song locator."""
    library = Library(library_uuid=None, name="x", root_path="/m")

    with pytest.raises(ValueError, match="has no library_uuid"):
        song_identity_for(library, "a.flac")


# ─────────────────────────────────────────────────────────────────────────
# detect_move_for_new_file
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_detect_move_returns_none_when_no_candidate() -> None:
    entry = _new_file_entry()

    with _patched_detection([]) as mock_candidate:
        result = detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False)

    assert result is None
    mock_candidate.assert_called_once()
    assert mock_candidate.call_args.args[1] is _LIBRARY
    assert mock_candidate.call_args.args[2] == "abc123"


@pytest.mark.unit
def test_detect_move_skips_self_match() -> None:
    """A candidate whose physical path equals the new path is a re-scan self match."""
    entry = _new_file_entry()
    self_match = _song(path=str(entry["path"]), normalized_path="new/song.flac")

    assert _detect(entry, [self_match]) is None


@pytest.mark.unit
def test_detect_move_skips_same_locator_candidate() -> None:
    """A candidate whose normalized path equals the new entry's own locator is the
    same row, not a move."""
    entry = _new_file_entry()
    same_locator = _song(path="D:/Other/song.flac", normalized_path="new/song.flac")

    assert _detect(entry, [same_locator]) is None


@pytest.mark.unit
def test_detect_move_rejects_candidate_outside_duration_tolerance() -> None:
    """When both durations are known and differ by more than 1 s, the candidate is a
    fingerprint collision, not a relocation."""
    entry = _new_file_entry(duration_seconds=181.5)
    candidate = _song("D:/Music/old/song.flac", "old/song.flac", duration_seconds=180.0)

    assert _detect(entry, [candidate]) is None


@pytest.mark.unit
def test_detect_move_accepts_candidate_within_duration_tolerance() -> None:
    entry = _new_file_entry(duration_seconds=180.9)
    candidate = _song("D:/Music/old/song.flac", "old/song.flac", duration_seconds=180.0)

    result = _detect(entry, [candidate])

    assert isinstance(result, FileMove)


@pytest.mark.unit
def test_detect_move_excludes_candidate_whose_source_is_present() -> None:
    """A live source (present on disk) is never a relocation origin."""
    entry = _new_file_entry()
    candidate = _song("D:/Music/old/song.flac", "old/song.flac")

    assert _detect(entry, [candidate], source_present=True) is None


@pytest.mark.unit
def test_detect_move_returns_file_move_for_exactly_one_absent_survivor() -> None:
    entry = _new_file_entry()
    candidate = _song("D:/Music/old/song.flac", "old/song.flac")

    result = _detect(entry, [candidate])

    assert isinstance(result, FileMove)
    assert result.old_path == "D:/Music/old/song.flac"
    assert result.new_path == "D:/Music/new/song.flac"
    assert result.song_identity == SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/song.flac")
    assert not hasattr(result, "song_id")
    assert result.chromaprint == "abc123"
    assert result.old_duration == 180.0
    assert result.new_duration == 180.0
    assert result.new_file_size == 1000
    assert result.new_modified_time == 2000


@pytest.mark.unit
def test_detect_move_preserves_candidate_duration_when_entry_has_none() -> None:
    """When the new entry carries no duration, the candidate's known duration is
    preserved on the returned move rather than dropped."""
    entry = _new_file_entry(duration_seconds=None)
    candidate = _song("D:/Music/old/song.flac", "old/song.flac", duration_seconds=181.0)

    result = _detect(entry, [candidate])

    assert isinstance(result, FileMove)
    assert result.new_duration == 181.0


@pytest.mark.unit
def test_detect_move_refuses_truncated_candidate_window() -> None:
    entry = _new_file_entry()
    visible_absent = _song("D:/Music/old/visible.flac", "old/visible.flac")
    outside_window_absent = _song("D:/Music/old/outside.flac", "old/outside.flac")

    with _patched_detection([visible_absent, outside_window_absent]) as mock_candidate:
        mock_candidate.return_value = ChromaprintSongMatches(songs=(visible_absent,), complete=False)
        result = detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False)

    assert result is None


@pytest.mark.unit
def test_detect_move_returns_none_for_ambiguous_multiple_survivors() -> None:
    entry = _new_file_entry()
    first = _song("D:/Music/old/a.flac", "old/a.flac")
    second = _song("D:/Music/old/b.flac", "old/b.flac")

    assert _detect(entry, [first, second]) is None


@pytest.mark.unit
def test_detect_move_returns_none_when_chromaprint_is_empty() -> None:
    entry = _new_file_entry()
    with (
        patch(f"{_COMPONENT}.build_library_path_from_input") as mock_build,
        patch(f"{_COMPONENT}.compute_chromaprint_for_file", return_value=""),
        patch(f"{_COMPONENT}.find_move_candidates_by_chromaprint") as mock_candidate,
    ):
        mock_build.return_value.is_valid.return_value = True
        assert detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False) is None
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_move_returns_none_when_library_path_invalid() -> None:
    """An unresolvable library-relative path is not decoded and never looked up."""
    entry = _new_file_entry()
    with (
        patch(f"{_COMPONENT}.build_library_path_from_input") as mock_build,
        patch(f"{_COMPONENT}.compute_chromaprint_for_file") as mock_chromaprint,
        patch(f"{_COMPONENT}.find_move_candidates_by_chromaprint") as mock_candidate,
    ):
        mock_build.return_value.is_valid.return_value = False
        mock_build.return_value.reason = "no library for path"
        result = detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False)

    assert result is None
    mock_chromaprint.assert_not_called()
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_move_returns_none_when_chromaprint_decode_raises_oserror() -> None:
    """A corrupt/unreadable new file is a safe miss: no candidate lookup runs."""
    entry = _new_file_entry()
    with (
        patch(f"{_COMPONENT}.build_library_path_from_input") as mock_build,
        patch(f"{_COMPONENT}.compute_chromaprint_for_file", side_effect=OSError("unreadable")),
        patch(f"{_COMPONENT}.find_move_candidates_by_chromaprint") as mock_candidate,
    ):
        mock_build.return_value.is_valid.return_value = True
        result = detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False)

    assert result is None
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_move_returns_none_when_chromaprint_decode_raises_runtimeerror() -> None:
    """A decoder runtime failure on the new file is also a safe miss."""
    entry = _new_file_entry()
    with (
        patch(f"{_COMPONENT}.build_library_path_from_input") as mock_build,
        patch(f"{_COMPONENT}.compute_chromaprint_for_file", side_effect=RuntimeError("decoder failed")),
        patch(f"{_COMPONENT}.find_move_candidates_by_chromaprint") as mock_candidate,
    ):
        mock_build.return_value.is_valid.return_value = True
        result = detect_move_for_new_file(entry, _LIBRARY, make_db(), source_present=lambda _song: False)

    assert result is None
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_move_skips_self_match_when_locator_absent() -> None:
    """The physical-path self-match guard fires independently of the same-locator
    guard: with no normalized locator on the entry, a candidate at the new file's
    own path must still be skipped (otherwise the row would move onto itself)."""
    entry = _new_file_entry(normalized_path=None)
    self_match = _song(path=str(entry["path"]), normalized_path="old/song.flac")

    assert _detect(entry, [self_match]) is None


@pytest.mark.unit
def test_detect_move_accepts_candidate_with_unknown_duration() -> None:
    """When the candidate's duration is unknown the tolerance check is skipped and
    the candidate is still a valid relocation origin."""
    entry = _new_file_entry(duration_seconds=180.0)
    candidate = _song("D:/Music/old/song.flac", "old/song.flac", duration_seconds=None)

    result = _detect(entry, [candidate])

    assert isinstance(result, FileMove)
    assert result.old_duration is None
    assert result.new_duration == 180.0


# ─────────────────────────────────────────────────────────────────────────
# relocate_song
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_relocate_song_builds_one_path_update_and_returns_true() -> None:
    db = make_db()
    source = SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/a.flac")
    destination = SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="new/a.flac")

    with patch(f"{_COMPONENT}.update_song_path") as mock_update:
        mock_update.return_value = destination
        result = relocate_song(
            db,
            source,
            new_path="/music/new/a.flac",
            normalized_path="new/a.flac",
            file_size=2048,
            modified_time=9999,
            duration_seconds=181.0,
        )

    assert result is True
    mock_update.assert_called_once()
    passed_db, command = mock_update.call_args.args
    assert passed_db is db
    assert isinstance(command, SongPathUpdate)
    assert command.song_identity == source
    assert not hasattr(command, "song_id")
    assert command.new_path == "/music/new/a.flac"
    assert isinstance(command.scan, SongScanUpdate)
    assert command.scan.normalized_path == "new/a.flac"
    assert command.scan.file_size == 2048
    assert command.scan.modified_time == 9999
    assert command.scan.duration_seconds == 181.0


@pytest.mark.unit
def test_relocate_song_returns_false_when_intent_returns_none() -> None:
    """A stale/missing source locator is a safe no-op miss (``False``)."""
    db = make_db()
    source = SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/a.flac")

    with patch(f"{_COMPONENT}.update_song_path", return_value=None):
        result = relocate_song(
            db,
            source,
            new_path="/music/new/a.flac",
            normalized_path="new/a.flac",
            file_size=2048,
            modified_time=9999,
            duration_seconds=181.0,
        )

    assert result is False
