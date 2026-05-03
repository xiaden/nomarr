"""Tests for nomarr.components.processing.file_write_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.processing.file_write_comp import (
    get_file_for_writing,
    get_nomarr_tags,
    mark_file_written,
    release_file_claim,
    resolve_library_root,
    save_mood_tags,
    save_mood_tags_batch,
)
from nomarr.helpers.dto.tags_dto import Tag, Tags


class TestGetFileForWriting:
    """Tests for ``get_file_for_writing()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_raw_key_to_prefixed_id(self) -> None:
        mock_db = MagicMock()
        file_doc = {"_id": "library_files/abc123"}

        with patch(
            "nomarr.components.processing.file_write_comp.get_file_by_id",
            return_value=file_doc,
        ) as mock_get_file_by_id:
            result = get_file_for_writing(mock_db, "abc123")

        assert result == ("library_files/abc123", "abc123", file_doc)
        mock_get_file_by_id.assert_called_once_with(mock_db, "library_files/abc123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_strips_prefix_from_already_prefixed_key(self) -> None:
        mock_db = MagicMock()
        file_doc = {"_id": "library_files/abc123"}

        with patch(
            "nomarr.components.processing.file_write_comp.get_file_by_id",
            return_value=file_doc,
        ) as mock_get_file_by_id:
            result = get_file_for_writing(mock_db, "library_files/abc123")

        assert result == ("library_files/abc123", "abc123", file_doc)
        mock_get_file_by_id.assert_called_once_with(mock_db, "library_files/abc123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_file_doc_when_not_found(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.processing.file_write_comp.get_file_by_id",
            return_value=None,
        ) as mock_get_file_by_id:
            result = get_file_for_writing(mock_db, "missing")

        assert result == ("library_files/missing", "missing", None)
        mock_get_file_by_id.assert_called_once_with(mock_db, "library_files/missing")


class TestResolveLibraryRoot:
    """Tests for ``resolve_library_root()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_library_missing(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.processing.file_write_comp.get_library_record",
            return_value=None,
        ) as mock_get_library_record:
            result = resolve_library_root(mock_db, "libraries/1")

        assert result is None
        mock_get_library_record.assert_called_once_with(mock_db, "libraries/1", include_scan=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_path_for_existing_library(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.processing.file_write_comp.get_library_record",
            return_value={"root_path": "/music"},
        ) as mock_get_library_record:
            result = resolve_library_root(mock_db, "libraries/1")

        assert result == Path("/music")
        mock_get_library_record.assert_called_once_with(mock_db, "libraries/1", include_scan=False)


class TestGetNomarrTags:
    """Tests for ``get_nomarr_tags()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_get_song_tags_with_nomarr_only(self) -> None:
        mock_db = MagicMock()
        returned_tags = MagicMock()

        with patch(
            "nomarr.components.processing.file_write_comp.get_song_tags",
            return_value=returned_tags,
        ) as mock_get_song_tags:
            result = get_nomarr_tags(mock_db, "library_files/abc123")

        assert result is returned_tags
        mock_get_song_tags.assert_called_once_with(mock_db, "library_files/abc123", nomarr_only=True)


class TestSaveMoodTags:
    """Tests for ``save_mood_tags()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_writes_three_tiers_always(self) -> None:
        mock_db = MagicMock()
        mood_tags = Tags(items=(Tag(key="mood-strict", value=("happy",)),))

        with patch("nomarr.components.processing.file_write_comp.set_song_tags") as mock_set_song_tags:
            result = save_mood_tags(mock_db, "library_files/abc123", mood_tags)

        assert result == 1
        mock_set_song_tags.assert_has_calls(
            [
                call(mock_db, "library_files/abc123", "nom:mood-strict", ["happy"]),
                call(mock_db, "library_files/abc123", "nom:mood-regular", []),
                call(mock_db, "library_files/abc123", "nom:mood-loose", []),
            ]
        )
        assert mock_set_song_tags.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_nonempty_tiers(self) -> None:
        mock_db = MagicMock()
        mood_tags = Tags(
            items=(
                Tag(key="nom:mood-strict", value=("happy",)),
                Tag(key="mood-regular", value=("calm", "warm")),
            )
        )

        with patch("nomarr.components.processing.file_write_comp.set_song_tags"):
            result = save_mood_tags(mock_db, "library_files/abc123", mood_tags)

        assert result == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_clears_absent_tiers_with_empty_list(self) -> None:
        mock_db = MagicMock()
        mood_tags = Tags(items=(Tag(key="nom:mood-loose", value=("chill",)),))

        with patch("nomarr.components.processing.file_write_comp.set_song_tags") as mock_set_song_tags:
            save_mood_tags(mock_db, "library_files/abc123", mood_tags)

        mock_set_song_tags.assert_any_call(mock_db, "library_files/abc123", "nom:mood-strict", [])
        mock_set_song_tags.assert_any_call(mock_db, "library_files/abc123", "nom:mood-regular", [])
        mock_set_song_tags.assert_any_call(mock_db, "library_files/abc123", "nom:mood-loose", ["chill"])


class TestSaveMoodTagsBatch:
    """Tests for ``save_mood_tags_batch()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_for_empty_items(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.processing.file_write_comp.set_song_tags_batch") as mock_set_song_tags_batch:
            result = save_mood_tags_batch(mock_db, [])

        assert result == 0
        mock_set_song_tags_batch.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_set_song_tags_batch(self) -> None:
        mock_db = MagicMock()
        mood_tags = Tags(items=(Tag(key="mood-strict", value=("happy",)),))
        items: list[tuple[str, Tags]] = [("library_files/abc123", mood_tags)]

        with patch(
            "nomarr.components.processing.file_write_comp.set_song_tags_batch",
        ) as mock_set_song_tags_batch:
            result = save_mood_tags_batch(mock_db, items)

        assert result == 1
        mock_set_song_tags_batch.assert_called_once_with(
            mock_db,
            [
                {"song_id": "library_files/abc123", "name": "nom:mood-strict", "values": ("happy",)},
                {"song_id": "library_files/abc123", "name": "nom:mood-regular", "values": []},
                {"song_id": "library_files/abc123", "name": "nom:mood-loose", "values": []},
            ],
        )


class TestReleaseFileClaim:
    """Tests for ``release_file_claim()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_release_claim(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.processing.file_write_comp.release_claim") as mock_release_claim:
            release_file_claim(mock_db, "abc123")

        mock_release_claim.assert_called_once_with(mock_db, "abc123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_exceptions(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.processing.file_write_comp.release_claim",
            side_effect=RuntimeError("boom"),
        ) as mock_release_claim:
            release_file_claim(mock_db, "abc123")

        mock_release_claim.assert_called_once_with(mock_db, "abc123")


class TestMarkFileWritten:
    """Tests for mark_file_written delegation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_library_files_set_file_written(self) -> None:
        mock_db = MagicMock()
        with patch("nomarr.components.processing.file_write_comp.set_file_written") as mock_set_file_written:
            mark_file_written(mock_db, "abc123")

        mock_set_file_written.assert_called_once_with(mock_db, "abc123")
