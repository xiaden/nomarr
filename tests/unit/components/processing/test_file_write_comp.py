"""Tests for nomarr.components.processing.file_write_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.processing.file_write_comp import (
    get_file_for_writing,
    release_file_claim,
    resolve_library_root,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) for write tests."""
    return Library(name="Test Library", root_path="/music")


class TestGetFileForWriting:
    """Tests for ``get_file_for_writing()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reads_song_using_supplied_locator(self) -> None:
        mock_db = MagicMock()
        identity = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")
        song = MagicMock()
        mock_db.library.get_song.return_value = song

        result = get_file_for_writing(mock_db, identity)

        assert result is song
        mock_db.library.get_song.assert_called_once_with(identity)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_locator_no_longer_resolves(self) -> None:
        mock_db = MagicMock()
        identity = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "missing.flac")
        mock_db.library.get_song.return_value = None

        result = get_file_for_writing(mock_db, identity)

        assert result is None
        mock_db.library.get_song.assert_called_once_with(identity)


class TestResolveLibraryRoot:
    """Tests for ``resolve_library_root()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_library_missing(self) -> None:
        mock_db = MagicMock()
        library = _make_library()

        with patch(
            "nomarr.components.processing.file_write_comp.get_library_record",
            return_value=None,
        ) as mock_get_library_record:
            result = resolve_library_root(mock_db, library)

        assert result is None
        mock_get_library_record.assert_called_once_with(mock_db, library, include_scan=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_path_for_existing_library(self) -> None:
        mock_db = MagicMock()
        library = _make_library()

        with patch(
            "nomarr.components.processing.file_write_comp.get_library_record",
            return_value=Library(name="Test Library", root_path="/music"),
        ) as mock_get_library_record:
            result = resolve_library_root(mock_db, library)

        assert result == Path("/music")
        mock_get_library_record.assert_called_once_with(mock_db, library, include_scan=False)


class TestReleaseFileClaim:
    """Tests for ``release_file_claim()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_release_claim(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")

        with patch("nomarr.components.processing.file_write_comp.release_claim") as mock_release_claim:
            release_file_claim(mock_db, song, "worker:write:0")

        mock_release_claim.assert_called_once_with(mock_db, song, "worker:write:0")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_exceptions(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")

        with patch(
            "nomarr.components.processing.file_write_comp.release_claim",
            side_effect=RuntimeError("boom"),
        ) as mock_release_claim:
            release_file_claim(mock_db, song, "worker:write:0")

        mock_release_claim.assert_called_once_with(mock_db, song, "worker:write:0")
