"""Tests for ``nomarr.components.library.move_detection_comp``.

Move detection now addresses detected moves by their **source locator**
``SongIdentity(library, normalized_path)`` (ADR-048) instead of a stable
``song_id``: ``detect_file_move_via_db`` takes the natural ``Library`` domain
value (never a numeric ``library_id``) and builds each ``FileMove`` source
identity from the library's natural key and the candidate row's
``normalized_path``. ``apply_detected_moves`` forwards that source locator,
reseed tags under the destination identity returned by the move intent, and
treats a stale/missing source (``None`` return) as a skip-and-continue miss.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.move_detection_comp import (
    FileMove,
    apply_detected_moves,
    detect_file_move_via_db,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
)


def make_db() -> MagicMock:
    """Build a mocked facade ``Database`` with sub-facades."""
    db = MagicMock()
    db.library = MagicMock()
    db.app = MagicMock()
    db.ml = MagicMock()
    return db


def _new_file_entry(**overrides: object) -> dict[str, object]:
    base: dict = {
        "path": "D:/Music/new/song.flac",
        "file_size": 1000,
        "modified_time": 2000,
        "duration_seconds": 180.0,
    }
    base.update(overrides)
    return base


def _mock_valid_library_path(mock_build: MagicMock) -> None:
    """Make ``build_library_path_from_input`` return a valid path handle."""
    mock_build.return_value.is_valid.return_value = True


_LIBRARY = Library(name="main", root_path="/music")
_LIBRARY_IDENTITY = LibraryIdentity(name="main", root_path="/music")


@pytest.mark.unit
def test_detect_file_move_via_db_returns_none_when_no_candidate() -> None:
    db = make_db()
    entry = _new_file_entry()

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        mock_candidate.return_value = None

        result = detect_file_move_via_db(entry, _LIBRARY, db)

    assert result is None
    mock_candidate.assert_called_once()


@pytest.mark.unit
def test_detect_file_move_via_db_skips_self_match() -> None:
    """A candidate whose physical path equals the new path is a re-scan self
    match, not a move."""
    db = make_db()
    entry = _new_file_entry()

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        mock_candidate.return_value = {
            "path": entry["path"],  # same path → self-match
            "normalized_path": "new/song.flac",
            "duration_seconds": 180.0,
        }

        result = detect_file_move_via_db(entry, _LIBRARY, db)

    assert result is None


@pytest.mark.unit
def test_detect_file_move_via_db_passes_library_domain_object_and_builds_source_locator() -> None:
    db = make_db()
    entry = _new_file_entry()
    candidate = {
        "path": "D:/Music/old/song.flac",
        "normalized_path": "old/song.flac",
        "duration_seconds": 180.0,
    }

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate_fn,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        mock_candidate_fn.return_value = candidate

        result = detect_file_move_via_db(entry, _LIBRARY, db)

    # The chromaprint lookup receives the passed natural Library domain object.
    mock_candidate_fn.assert_called_once()
    args = mock_candidate_fn.call_args.args
    passed_library = args[1]
    assert isinstance(passed_library, Library)
    assert passed_library.name == "main"
    assert passed_library.root_path == "/music"
    assert args[2] == "abc123"

    assert isinstance(result, FileMove)
    assert result.old_path == "D:/Music/old/song.flac"
    assert result.new_path == "D:/Music/new/song.flac"
    # The move is addressed by its source SongIdentity locator (library + source
    # normalized_path), NOT a stable song_id / row id.
    assert result.song_identity == SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/song.flac")
    assert not hasattr(result, "song_id")
    assert result.chromaprint == "abc123"


def _move(**overrides: object) -> FileMove:
    """Build a canonical detected ``FileMove`` (source-locator addressing)."""
    base: dict = {
        "song_identity": SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/a.flac"),
        "old_path": "/music/old/a.flac",
        "new_path": "/music/new/a.flac",
        "chromaprint": "cp-a-flac",
        "old_duration": 180.0,
        "new_duration": 181.0,
        "new_file_size": 2048,
        "new_modified_time": 9999,
    }
    base.update(overrides)
    return FileMove(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestApplyDetectedMoves:
    """``apply_detected_moves`` (the actual owner of a bulk move) drives one
    atomic move intent per move addressed by the source SongIdentity locator."""

    def _make_db(self) -> MagicMock:
        db = make_db()

        def _destination(command: SongPathUpdate) -> SongIdentity:
            return SongIdentity(library=command.song_identity.library, normalized_path=command.scan.normalized_path)

        # On a successful move the intent returns the DESTINATION locator.
        db.library.move_library_song.side_effect = _destination
        return db

    def _patch_entity_tags(self, mock_build: MagicMock) -> None:
        """Return a truthy assignment list so reseeding runs."""
        mock_build.return_value = [MagicMock()]

    def test_persists_one_move_intent_with_source_locator(self) -> None:
        db = self._make_db()
        move = _move()

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags"),
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            self._patch_entity_tags(mock_build)
            applied = apply_detected_moves([move], {move.new_path: {"title": "A"}}, db, Path("/music"))

        assert applied == 1
        # Exactly ONE move-intent facade call per move carrying the source
        # SongIdentity locator (never a song_id / natural path separately).
        db.library.move_library_song.assert_called_once()
        command = db.library.move_library_song.call_args.args[0]
        assert isinstance(command, SongPathUpdate)
        assert command.song_identity == move.song_identity
        assert command.song_identity.library == _LIBRARY_IDENTITY
        assert command.song_identity.normalized_path == "old/a.flac"
        assert not hasattr(command, "song_id")
        assert command.new_path == "/music/new/a.flac"
        assert isinstance(command.scan, SongScanUpdate)
        assert command.scan.file_size == 2048
        assert command.scan.modified_time == 9999
        assert command.scan.duration_seconds == 181.0

    def test_computes_normalized_path_from_library_root(self) -> None:
        db = self._make_db()
        move = _move()

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.return_value = []
            mock_build.return_value = []
            apply_detected_moves([move], {}, db, Path("/music"))

        command = db.library.move_library_song.call_args.args[0]
        assert command.scan.normalized_path == "new/a.flac"

    def test_out_of_root_destination_aborts_before_any_write(self) -> None:
        """A destination outside the library root keeps the defensive None
        normalized-path fallback. The real facade raises ValueError BEFORE any
        write for a None normalized_path (songs.normalized_path is NOT NULL) and
        never returns a destination, so the abort contract must hold: the move is
        never applied (no destination locator, no reseed) and the ValueError
        propagates out of apply_detected_moves."""
        db = self._make_db()
        move = _move(new_path="/elsewhere/b.flac")
        db.library.move_library_song.side_effect = ValueError("move_library_song() requires a normalized_path")

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags"),
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments"),
            pytest.raises(ValueError, match="normalized_path"),
        ):
            apply_detected_moves([move], {}, db, Path("/music"))

        # The None-normalized-path command is what persistence rejects; exactly
        # one move-intent call is issued and no reseed (destination) is resolved.
        command = db.library.move_library_song.call_args.args[0]
        assert command.scan.normalized_path is None
        db.library.move_library_song.assert_called_once()
        db.library.resolve_song_identity.assert_not_called()

    def test_reseeds_entity_tags_under_destination_identity(self) -> None:
        db = self._make_db()
        move = _move()
        assignments = [MagicMock()]
        destination = SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="new/a.flac")

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.return_value = [{"name": "artist", "value": "X"}]
            mock_build.return_value = assignments
            applied = apply_detected_moves([move], {move.new_path: {"artist": "X"}}, db, Path("/music"))

        assert applied == 1
        mock_extract.assert_called_once_with({"artist": "X"})
        # build_song_tag_assignments keeps its compute-only int API; the caller
        # passes the existing 0 sentinel — no numeric identity migration.
        mock_build.assert_called_once_with(0, [{"name": "artist", "value": "X"}])
        # Tags are re-seeded under the DESTINATION locator returned by the move
        # intent (after a successful move the source locator no longer resolves);
        # the retired numeric resolve_song_identity(source song_id) bridge is gone.
        db.library.resolve_song_identity.assert_not_called()
        db.library.replace_song_tags.assert_called_once_with(destination, assignments)

    def test_counts_applied_and_reseeds_per_move(self) -> None:
        db = self._make_db()
        move_a = _move(new_path="/music/new/a.flac")
        move_b = _move(
            song_identity=SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/b.flac"),
            new_path="/music/new/b.flac",
        )
        metadata = {
            move_a.new_path: {"artist": "A"},
            move_b.new_path: {"artist": "B"},
        }

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.side_effect = lambda meta: [meta]
            mock_build.side_effect = lambda *_args, **_kwargs: [MagicMock()]
            applied = apply_detected_moves([move_a, move_b], metadata, db, Path("/music"))

        assert applied == 2
        assert db.library.move_library_song.call_count == 2
        # One reseed per moved song under its own destination identity.
        assert db.library.replace_song_tags.call_count == 2
        db.library.resolve_song_identity.assert_not_called()

    def test_skips_reseed_when_no_metadata_but_still_applies(self) -> None:
        db = self._make_db()
        move = _move()

        applied = apply_detected_moves([move], {}, db, Path("/music"))

        assert applied == 1
        db.library.move_library_song.assert_called_once()
        db.library.resolve_song_identity.assert_not_called()
        db.library.replace_song_tags.assert_not_called()

    def test_logs_warning_and_still_applies_when_reseed_fails(self) -> None:
        db = self._make_db()
        move = _move()
        db.library.replace_song_tags.side_effect = RuntimeError("reseed boom")

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
            patch("nomarr.components.library.move_detection_comp.logger.warning") as mock_warn,
        ):
            mock_extract.return_value = [{"artist": "X"}]
            mock_build.return_value = [MagicMock()]
            applied = apply_detected_moves([move], {move.new_path: {"artist": "X"}}, db, Path("/music"))

        # A reseed failure is logged and does NOT roll back / abort the move.
        assert applied == 1
        mock_warn.assert_called_once()
        db.library.move_library_song.assert_called_once()

    def test_stale_source_skips_and_continues(self) -> None:
        """A stale/missing source locator (move intent returns None) is a safe
        no-op miss (ADR-048 §5): the move is not applied, no reseed runs, and
        processing continues to the next move."""
        db = self._make_db()
        move_a = _move()
        move_b = _move(
            song_identity=SongIdentity(library=_LIBRARY_IDENTITY, normalized_path="old/b.flac"),
            new_path="/music/new/b.flac",
        )

        def _dest_or_none(command: SongPathUpdate) -> SongIdentity | None:
            if command.song_identity.normalized_path == "old/a.flac":
                return None  # stale source for the first move
            return SongIdentity(library=command.song_identity.library, normalized_path=command.scan.normalized_path)

        db.library.move_library_song.side_effect = _dest_or_none
        db.library.replace_song_tags.reset_mock()

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
            patch("nomarr.components.library.move_detection_comp.logger.warning") as mock_warn,
        ):
            mock_extract.side_effect = lambda meta: [meta]
            mock_build.return_value = [MagicMock()]
            applied = apply_detected_moves([move_a, move_b], {move_b.new_path: {"artist": "B"}}, db, Path("/music"))

        # move_a skipped (stale), move_b applied.
        assert applied == 1
        assert db.library.move_library_song.call_count == 2
        # No reseed ran for the stale move; one reseed for move_b.
        assert db.library.replace_song_tags.call_count == 1
        mock_warn.assert_called_once()

    def test_persistence_failure_propagates_and_is_not_reported_applied(self) -> None:
        """A persistence failure in the move intent propagates to the caller (the
        historical abort-on-first contract); the failed move is never reported
        applied and its reseed never runs."""
        db = self._make_db()
        move = _move()
        db.library.move_library_song.side_effect = RuntimeError("db down")

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags"),
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments"),
            pytest.raises(RuntimeError, match="db down"),
        ):
            apply_detected_moves([move], {move.new_path: {"artist": "X"}}, db, Path("/music"))

        db.library.move_library_song.assert_called_once()
        db.library.resolve_song_identity.assert_not_called()
