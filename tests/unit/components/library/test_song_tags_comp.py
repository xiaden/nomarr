"""Tests for ``nomarr.components.library.song_tags_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.song_tags_comp import get_song_tags_with_path
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.library_dto import FileTag


def _song(**overrides: object) -> Song:
    base: dict = {
        "song_id": 1,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


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
        file_doc = _song(path="D:/Music/song.flac")
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
        file_doc = _song(path="D:/Music/song.flac")
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "nom:mood", "value": "happy", "namespace": "nom"},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [FileTag(key="nom:mood", value="happy", tag_type="string", is_nomarr=True)],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_tag_rows_have_library_file_tag_contract(self) -> None:
        """The component boundary must expose library ``FileTag`` objects."""
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = _song(path="D:/Music/song.flac")
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "tempo", "value": 120, "namespace": ""},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result is not None
        assert result["tags"][0] == FileTag(key="tempo", value="120", tag_type="float", is_nomarr=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transforms_multi_value_tags_to_individual_entries(self) -> None:
        mock_db = MagicMock()
        file_doc = _song(path="D:/Music/song.flac")
        mock_db.library.get_song.return_value = file_doc
        mock_db.library.list_tags_for_song.return_value = [
            {"name": "genre", "value": "a", "namespace": ""},
            {"name": "genre", "value": "b", "namespace": ""},
        ]

        result = get_song_tags_with_path(mock_db, 1)

        assert result == {
            "path": "D:/Music/song.flac",
            "tags": [
                FileTag(key="genre", value="a", tag_type="string", is_nomarr=False),
                FileTag(key="genre", value="b", tag_type="string", is_nomarr=False),
            ],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_nomarr_only_flag(self) -> None:
        mock_db = MagicMock()
        file_doc = _song(path="D:/Music/song.flac")
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
            "tags": [FileTag(key="nom:mood", value="happy", tag_type="string", is_nomarr=True)],
        }
