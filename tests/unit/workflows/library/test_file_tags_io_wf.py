"""Tests for nomarr.workflows.library.file_tags_io_wf module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow


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
