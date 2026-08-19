"""Tests for ``nomarr.components.library.song_tags_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.song_tags_comp import get_song_tags_with_path


class TestGetFileTagsWithPath:
    """Tests for ``get_song_tags_with_path()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_file_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = None

        result = get_song_tags_with_path(mock_db, 1)

        assert result is None
        mock_db.library.get_song.assert_called_once_with(1)
        mock_db.library.list_tags_for_song.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_path_and_empty_tags_when_no_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = []

        result = get_song_tags_with_path(mock_db, 1)

        assert result == {"path": "D:/Music/song.flac", "tags": []}
        mock_db.library.get_song.assert_called_once_with(1)
        mock_db.library.list_tags_for_song.assert_called_once_with(1)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_single_value_tags(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "nom:mood", "value": "happy", "namespace": "nom"},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "nom:mood",
                    "value": "happy",
                    "type": "string",
                    "is_nomarr": True,
                }
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_tag_rows_have_canonical_keys(self) -> None:
        """The component boundary must expose the canonical tag row contract."""
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = {"path": "D:/Music/song.flac"}
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "tempo", "value": 120, "namespace": ""},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result is not None
        assert set(result["tags"][0]) == {"key", "value", "type", "is_nomarr"}
        assert result["tags"][0] == {
            "key": "tempo",
            "value": 120,
            "type": "float",
            "is_nomarr": False,
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_multi_value_tags_to_individual_entries(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "genre", "value": "a", "namespace": ""},
            {"name": "genre", "value": "b", "namespace": ""},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "genre",
                    "value": "a",
                    "type": "string",
                    "is_nomarr": False,
                },
                {
                    "key": "genre",
                    "value": "b",
                    "type": "string",
                    "is_nomarr": False,
                },
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_nomarr_only_flag(self) -> None:
        mock_db = MagicMock()
        file_doc = {"path": "D:/Music/song.flac"}
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "nom:mood", "value": "happy", "namespace": "nom"},
            {"name": "genre", "value": "a", "namespace": ""},
        ]

        result = get_song_tags_with_path(mock_db, 1, nomarr_only=True)

        mock_db.library.list_tags_for_song.assert_called_once_with(1)
        # nomarr_only=True must exclude non-nomarr tags from the result.
        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                {
                    "key": "nom:mood",
                    "value": "happy",
                    "type": "string",
                    "is_nomarr": True,
                }
            ],
        }
