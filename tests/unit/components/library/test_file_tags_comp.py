"""Tests for ``nomarr.components.library.file_tags_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.file_tags_comp import get_file_tags_with_path
from nomarr.helpers.dataclasses.tags_dataclass import Tag


class TestGetFileTagsWithPath:
    """Tests for ``get_file_tags_with_path()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_file_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get_file.return_value = None

        result = get_file_tags_with_path(mock_db, f"{'library_files'}/missing")

        assert result is None
        mock_db.library_files.get_file.assert_called_once_with(f"{'library_files'}/missing")
        mock_db.tags.get_song_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_path_and_empty_tags_when_no_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library_files.get_file.return_value = file_doc
        mock_db.tags.get_song_tags.return_value = []

        result = get_file_tags_with_path(mock_db, f"{'library_files'}/1")

        assert result == {"path": "D:/Music/song.flac", "tags": []}
        mock_db.library_files.get_file.assert_called_once_with(f"{'library_files'}/1")
        mock_db.tags.get_song_tags.assert_called_once_with(f"{'library_files'}/1", nomarr_only=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_single_value_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library_files.get_file.return_value = file_doc
        tag = Tag(name="nom:mood", values=("happy",))
        mock_db.tags.get_song_tags.return_value = [tag]

        result = get_file_tags_with_path(mock_db, f"{'library_files'}/1")

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "nom:mood",
                    "name": "nom:mood",
                    "value": "happy",
                    "is_nomarr_tag": True,
                }
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_multi_value_tags_to_individual_entries(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library_files.get_file.return_value = file_doc
        tag = Tag(name="genre", values=("a", "b"))
        mock_db.tags.get_song_tags.return_value = [tag]

        result = get_file_tags_with_path(mock_db, f"{'library_files'}/1")

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "genre",
                    "name": "genre",
                    "value": "a",
                    "is_nomarr_tag": False,
                },
                {
                    "key": "genre",
                    "name": "genre",
                    "value": "b",
                    "is_nomarr_tag": False,
                },
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_nomarr_only_flag(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library_files.get_file.return_value = file_doc
        mock_db.tags.get_song_tags.return_value = []

        get_file_tags_with_path(mock_db, f"{'library_files'}/1", nomarr_only=True)

        mock_db.tags.get_song_tags.assert_called_once_with(f"{'library_files'}/1", nomarr_only=True)
