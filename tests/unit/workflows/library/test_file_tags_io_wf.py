"""Tests for nomarr.workflows.library.file_tags_io_wf module."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack"


def _real_library_path(target: Path) -> LibraryPath:
    return LibraryPath(relative=target.name, absolute=target, library_id=1, status="valid")


def _valid_library_path(relative: str) -> LibraryPath:
    return LibraryPath(
        relative=relative,
        absolute=Path("/music") / relative,
        library_id=1,
        status="valid",
    )


class TestReadFileTagsWorkflow:
    """Tests for ``read_file_tags_workflow()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_when_reader_returns_none(self) -> None:
        """No namespaced tags on disk map to an empty dict (strict None state)."""
        mock_db = MagicMock()
        lib_path = _valid_library_path("song.mp3")

        with (
            patch(
                "nomarr.workflows.library.file_tags_io_wf.build_library_path_from_input",
                return_value=lib_path,
            ),
            patch(
                "nomarr.workflows.library.file_tags_io_wf.read_tags_from_file",
                return_value=None,
            ),
        ):
            result = read_file_tags_workflow(mock_db, "song.mp3", "nom")

        assert result == {}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_dict_with_tuple_values_on_success(self) -> None:
        mock_db = MagicMock()
        lib_path = _valid_library_path("song.mp3")
        tags = Tags(items=(Tag(name="genre", values=("rock", "pop")),))

        with (
            patch(
                "nomarr.workflows.library.file_tags_io_wf.build_library_path_from_input",
                return_value=lib_path,
            ),
            patch(
                "nomarr.workflows.library.file_tags_io_wf.read_tags_from_file",
                return_value=tags,
            ),
        ):
            result = read_file_tags_workflow(mock_db, "song.mp3", "nom")

        assert result == {"genre": ("rock", "pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_for_invalid_path(self) -> None:
        mock_db = MagicMock()
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )

        with (
            patch(
                "nomarr.workflows.library.file_tags_io_wf.build_library_path_from_input",
                return_value=lib_path,
            ),
            pytest.raises(ValueError, match="Invalid path"),
        ):
            read_file_tags_workflow(mock_db, "song.mp3", "nom")


class TestReadFileTagsWorkflowRealCallerPath:
    """Real-caller path: ``TagWriter`` writes to disk, ``read_file_tags_workflow`` reads it back.

    Only the ``build_library_path_from_input`` DB resolver is patched (the workflow receives a
    ``MagicMock`` db); the real ``read_file_tags_workflow`` -> ``read_tags_from_file`` chain runs
    over the real fixture copy written by the real ``TagWriter``.
    """

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize("ext", ["flac", "ogg", "opus"])
    def test_vorbis_write_then_read_back_through_workflow(self, tmp_path: Path, ext: str) -> None:
        target = tmp_path / f"cooltrack.{ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{ext}", target)
        lib_path = _real_library_path(target)
        TagWriter().write(lib_path, Tags(items=(Tag(name="genre", values=("rock",)),)))

        with patch(
            "nomarr.workflows.library.file_tags_io_wf.build_library_path_from_input",
            return_value=lib_path,
        ):
            result = read_file_tags_workflow(MagicMock(), str(target), "nom")

        assert result == {"genre": ("rock",)}
