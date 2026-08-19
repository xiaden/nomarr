"""Tests for nomarr.components.tagging.tagging_writer_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.safe_write_comp import SafeWriteResult
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath


def _valid_library_path(relative: str) -> LibraryPath:
    return LibraryPath(
        relative=relative,
        absolute=Path("/music") / relative,
        library_id=1,
        status="valid",
    )


def _make_tags() -> Tags:
    return Tags(items=(Tag(name="genre", values=("rock", "pop")),))


class TestTagWriterWrite:
    """Tests for ``TagWriter.write()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_with_tags_delegates_to_format_writer_with_to_dict(self) -> None:
        writer = TagWriter()
        writer._mp3 = MagicMock()
        lib_path = _valid_library_path("song.mp3")
        tags = _make_tags()

        writer.write(lib_path, tags)

        writer._mp3.write.assert_called_once_with(lib_path, {"genre": ("rock", "pop")})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_with_none_clears_namespace_with_empty_dict(self) -> None:
        writer = TagWriter()
        writer._mp3 = MagicMock()
        lib_path = _valid_library_path("song.mp3")

        writer.write(lib_path, None)

        writer._mp3.write.assert_called_once_with(lib_path, {})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_routes_by_extension(self) -> None:
        writer = TagWriter()
        writer._mp4 = MagicMock()
        lib_path = _valid_library_path("song.m4a")

        writer.write(lib_path, _make_tags())

        writer._mp4.write.assert_called_once_with(lib_path, {"genre": ("rock", "pop")})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_raises_value_error_for_invalid_path(self) -> None:
        writer = TagWriter()
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        with pytest.raises(ValueError, match="invalid path"):
            writer.write(lib_path, _make_tags())


class TestTagWriterWriteSafe:
    """Tests for ``TagWriter.write_safe()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_with_none_clears_namespace_with_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writer = TagWriter()
        writer._write_to_path = MagicMock()

        def fake_safe_write_tags(path, library_root, write_fn, expected_mtime_ms) -> SafeWriteResult:
            write_fn(Path("/tmp/temp.flac"))
            return SafeWriteResult(success=True, error=None)

        monkeypatch.setattr(
            "nomarr.components.tagging.tagging_writer_comp.safe_write_tags",
            fake_safe_write_tags,
        )

        lib_path = _valid_library_path("song.flac")
        result = writer.write_safe(lib_path, None, library_root=Path("/music"), expected_mtime_ms=1000)

        assert result.success is True
        writer._write_to_path.assert_called_once()
        assert writer._write_to_path.call_args.args[1] == {}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_with_tags_passes_to_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writer = TagWriter()
        writer._write_to_path = MagicMock()

        def fake_safe_write_tags(path, library_root, write_fn, expected_mtime_ms) -> SafeWriteResult:
            write_fn(Path("/tmp/temp.flac"))
            return SafeWriteResult(success=True, error=None)

        monkeypatch.setattr(
            "nomarr.components.tagging.tagging_writer_comp.safe_write_tags",
            fake_safe_write_tags,
        )

        lib_path = _valid_library_path("song.flac")
        result = writer.write_safe(lib_path, _make_tags(), library_root=Path("/music"), expected_mtime_ms=1000)

        assert result.success is True
        assert writer._write_to_path.call_args.args[1] == {"genre": ("rock", "pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_returns_failure_for_invalid_path(self) -> None:
        writer = TagWriter()
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        result = writer.write_safe(lib_path, _make_tags(), library_root=Path("/music"), expected_mtime_ms=1000)
        assert result.success is False
        assert "Invalid path" in (result.error or "")
