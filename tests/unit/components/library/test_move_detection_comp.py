"""Tests for ``nomarr.components.library.move_detection_comp``.

Covers the identity-bridge None-safe paths in ``detect_file_move_via_db``:
the numeric ``library_id`` is resolved to a domain ``LibraryIdentity`` and then
to a ``Library`` before the chromaprint lookup — so the lookup must receive a
``Library`` domain object, never a raw int, and every missing-link step must
short-circuit to ``None`` without touching the next lookup.
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


@pytest.mark.unit
def test_detect_file_move_via_db_returns_none_when_library_identity_missing() -> None:
    db = make_db()
    entry = _new_file_entry()

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        db.library.resolve_library_identity.return_value = None

        result = detect_file_move_via_db(entry, 9, db)

    assert result is None
    db.library.resolve_library_identity.assert_called_once_with(9)
    db.library.get_library_by_name.assert_not_called()
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_file_move_via_db_returns_none_when_library_missing() -> None:
    db = make_db()
    entry = _new_file_entry()

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        db.library.resolve_library_identity.return_value = LibraryIdentity(name="main", root_path="/music")
        db.library.get_library_by_name.return_value = None

        result = detect_file_move_via_db(entry, 9, db)

    assert result is None
    db.library.resolve_library_identity.assert_called_once_with(9)
    db.library.get_library_by_name.assert_called_once_with("main")
    mock_candidate.assert_not_called()


@pytest.mark.unit
def test_detect_file_move_via_db_passes_library_domain_object_to_chromaprint_lookup() -> None:
    db = make_db()
    entry = _new_file_entry()

    resolved_library = Library(name="main", root_path="/music")
    candidate = {
        "id": 9,
        "path": "D:/Music/old/song.flac",
        "duration_seconds": 180.0,
    }

    with (
        patch("nomarr.components.library.move_detection_comp.build_library_path_from_input") as mock_build,
        patch("nomarr.components.library.move_detection_comp.compute_chromaprint_for_file") as mock_chromaprint,
        patch("nomarr.components.library.move_detection_comp.find_move_candidate_by_chromaprint") as mock_candidate_fn,
    ):
        _mock_valid_library_path(mock_build)
        mock_chromaprint.return_value = "abc123"
        db.library.resolve_library_identity.return_value = LibraryIdentity(name="main", root_path="/music")
        db.library.get_library_by_name.return_value = resolved_library
        mock_candidate_fn.return_value = candidate

        result = detect_file_move_via_db(entry, 9, db)

    # The chromaprint lookup must receive the Library domain object (natural
    # identity), never the raw int library_id.
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
    # The detected-move handle is the stable Song application identity (ADR-047
    # §8), populated from the candidate row's "id" — not an opaque file_id.
    assert result.song_id == 9
    assert result.chromaprint == "abc123"


def _move(**overrides: object) -> FileMove:
    """Build a canonical detected ``FileMove`` (stable ``song_id`` handle)."""
    base: dict = {
        "song_id": 7,
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
    atomic move intent per move with the stable Song identity."""

    def _make_db(self) -> MagicMock:
        db = make_db()
        db.library.resolve_song_identity.return_value = SongIdentity(
            library=LibraryIdentity(name="main", root_path="/music"),
            normalized_path="new/a.flac",
        )
        return db

    def _patch_entity_tags(self, mock_build: MagicMock) -> None:
        """Return a truthy assignment list so reseeding runs."""
        mock_build.return_value = [MagicMock()]

    def test_persists_one_move_intent_with_stable_song_identity(self) -> None:
        db = self._make_db()
        move = _move()

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags"),
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            self._patch_entity_tags(mock_build)
            applied = apply_detected_moves([move], {move.new_path: {"title": "A"}}, db, Path("/music"))

        assert applied == 1
        # Exactly ONE move-intent facade call per move, carrying the stable
        # Song identity (never a natural (library, path) locator).
        db.library.move_library_song.assert_called_once()
        command = db.library.move_library_song.call_args.args[0]
        assert isinstance(command, SongPathUpdate)
        assert command.song_id == 7
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

    def test_out_of_root_destination_uses_none_normalized_path(self) -> None:
        """A destination outside the library root keeps the defensive None
        normalized-path fallback; persistence owns the atomic rejection."""
        db = self._make_db()
        move = _move(new_path="/elsewhere/b.flac")

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.return_value = []
            mock_build.return_value = []
            apply_detected_moves([move], {}, db, Path("/music"))

        command = db.library.move_library_song.call_args.args[0]
        assert command.scan.normalized_path is None

    def test_reseeds_entity_tags_under_stable_identity(self) -> None:
        db = self._make_db()
        move = _move()
        assignments = [MagicMock()]
        identity = db.library.resolve_song_identity.return_value

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.return_value = [{"name": "artist", "value": "X"}]
            mock_build.return_value = assignments
            apply_detected_moves([move], {move.new_path: {"artist": "X"}}, db, Path("/music"))

        mock_extract.assert_called_once_with({"artist": "X"})
        mock_build.assert_called_once_with(7, [{"name": "artist", "value": "X"}])
        # Entity tags are re-seeded under the SAME stable Song identity.
        db.library.resolve_song_identity.assert_called_once_with(7)
        db.library.replace_song_tags.assert_called_once_with(identity, assignments)

    def test_counts_applied_and_reseeds_per_move(self) -> None:
        db = self._make_db()
        move_a = _move(song_id=7, new_path="/music/new/a.flac")
        move_b = _move(song_id=8, new_path="/music/new/b.flac")
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
        # One reseed per moved song under its own stable identity.
        assert db.library.resolve_song_identity.call_count == 2
        assert db.library.replace_song_tags.call_count == 2

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

    def test_skips_reseed_when_song_missing_after_move(self) -> None:
        db = self._make_db()
        move = _move()
        db.library.resolve_song_identity.return_value = None

        with (
            patch("nomarr.components.library.move_detection_comp._extract_entity_tags") as mock_extract,
            patch("nomarr.components.library.move_detection_comp.build_song_tag_assignments") as mock_build,
        ):
            mock_extract.return_value = [{"artist": "X"}]
            mock_build.return_value = [MagicMock()]
            applied = apply_detected_moves([move], {move.new_path: {"artist": "X"}}, db, Path("/music"))

        assert applied == 1
        db.library.resolve_song_identity.assert_called_once_with(7)
        db.library.replace_song_tags.assert_not_called()

    def test_persistence_failure_propagates_and_is_not_reported_applied(self) -> None:
        """A persistence failure in the move intent propagates to the caller (the
        current error-handling contract); the failed move is never reported
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
