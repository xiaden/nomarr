"""Tests for ``nomarr.components.library.file_tags_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.file_tags_comp import get_file_tags_with_path


class TestGetFileTagsWithPath:
    """Tests for ``get_file_tags_with_path()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_file_not_found(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.file_tags_comp.get_file_by_id",
                return_value=None,
            ) as mock_get_file_by_id,
            patch(
                "nomarr.components.library.file_tags_comp.get_song_tags",
            ) as mock_get_song_tags,
        ):
            result = get_file_tags_with_path(mock_db, "library_files/missing")

        assert result is None
        mock_get_file_by_id.assert_called_once_with(mock_db, "library_files/missing")
        mock_get_song_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_path_and_empty_tags_when_no_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}

        with (
            patch(
                "nomarr.components.library.file_tags_comp.get_file_by_id",
                return_value=file_doc,
            ) as mock_get_file_by_id,
            patch(
                "nomarr.components.library.file_tags_comp.get_song_tags",
                return_value=[],
            ) as mock_get_song_tags,
        ):
            result = get_file_tags_with_path(mock_db, "library_files/1")

        assert result == {"path": "D:/Music/song.flac", "tags": []}
        mock_get_file_by_id.assert_called_once_with(mock_db, "library_files/1")
        mock_get_song_tags.assert_called_once_with(mock_db, "library_files/1", nomarr_only=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_single_value_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        tag = MagicMock()
        tag.key = "nom:mood"
        tag.value = ["happy"]

        with (
            patch(
                "nomarr.components.library.file_tags_comp.get_file_by_id",
                return_value=file_doc,
            ),
            patch(
                "nomarr.components.library.file_tags_comp.get_song_tags",
                return_value=[tag],
            ),
        ):
            result = get_file_tags_with_path(mock_db, "library_files/1")

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
    def test_transforms_multi_value_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        tag = MagicMock()
        tag.key = "genre"
        tag.value = ["a", "b"]

        with (
            patch(
                "nomarr.components.library.file_tags_comp.get_file_by_id",
                return_value=file_doc,
            ),
            patch(
                "nomarr.components.library.file_tags_comp.get_song_tags",
                return_value=[tag],
            ),
        ):
            result = get_file_tags_with_path(mock_db, "library_files/1")

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "genre",
                    "name": "genre",
                    "value": ["a", "b"],
                    "is_nomarr_tag": False,
                }
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_nomarr_only_flag(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}

        with (
            patch(
                "nomarr.components.library.file_tags_comp.get_file_by_id",
                return_value=file_doc,
            ),
            patch(
                "nomarr.components.library.file_tags_comp.get_song_tags",
                return_value=[],
            ) as mock_get_song_tags,
        ):
            get_file_tags_with_path(mock_db, "library_files/1", nomarr_only=True)

        mock_get_song_tags.assert_called_once_with(mock_db, "library_files/1", nomarr_only=True)
