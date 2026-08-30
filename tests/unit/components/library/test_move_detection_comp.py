"""Tests for ``nomarr.components.library.move_detection_comp``.

Covers the identity-bridge None-safe paths in ``detect_file_move_via_db``:
the numeric ``library_id`` is resolved to a domain ``LibraryIdentity`` and then
to a ``Library`` before the chromaprint lookup — so the lookup must receive a
``Library`` domain object, never a raw int, and every missing-link step must
short-circuit to ``None`` without touching the next lookup.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.move_detection_comp import FileMove, detect_file_move_via_db
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity


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
    assert result.file_id == 9
    assert result.chromaprint == "abc123"
