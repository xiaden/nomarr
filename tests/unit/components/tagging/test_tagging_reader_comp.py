"""Tests for nomarr.components.tagging.tagging_reader_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nomarr.components.tagging.tagging_reader_comp import read_tags_from_file
from nomarr.helpers.dto.path_dto import LibraryPath


class _FakeFrame:
    """Minimal stand-in for a mutagen frame exposing a ``.text`` attribute."""

    def __init__(self, text: list[str]) -> None:
        self.text = text


def _valid_library_path(relative: str) -> LibraryPath:
    """Build a valid LibraryPath for testing (direct construction is test-only)."""
    return LibraryPath(
        relative=relative,
        absolute=Path("/music") / relative,
        library_id=1,
        status="valid",
    )


class TestReadTagsFromFile:
    """Tests for ``read_tags_from_file()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_valid_tags_when_namespaced_tags_exist(self) -> None:
        """Namespaced MP3 TXXX frames become a non-empty Tags object."""
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {
            "TXXX:nom:genre": _FakeFrame(["rock"]),
            "TXXX:nom:mood": _FakeFrame(["calm", "bright"]),
        }
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is not None
        assert result.to_dict() == {"genre": ("rock",), "mood": ("calm", "bright")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_namespaced_tags_match(self) -> None:
        """Frames without the namespace prefix are ignored, yielding None."""
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {
            "TXXX:other:genre": _FakeFrame(["rock"]),
            "TPE1": _FakeFrame(["artist"]),
        }
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_tag_dict_at_all(self) -> None:
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {}
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_for_invalid_path(self) -> None:
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        with pytest.raises(ValueError, match="invalid path"):
            read_tags_from_file(lib_path, "nom")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_runtime_error_when_mutagen_cannot_load(self) -> None:
        """A failed mutagen load surfaces as RuntimeError (wrapped ValueError)."""
        lib_path = _valid_library_path("song.mp3")

        with (
            patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=None),
            pytest.raises(RuntimeError, match="Failed to read tags"),
        ):
            read_tags_from_file(lib_path, "nom")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_runtime_error_for_unsupported_format(self) -> None:
        """An unsupported extension surfaces as RuntimeError (wrapped ValueError)."""
        lib_path = _valid_library_path("song.wav")

        with pytest.raises(RuntimeError, match="Unsupported audio format"):
            read_tags_from_file(lib_path, "nom")
