"""Tests for nomarr.components.processing.file_write_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.processing.file_write_comp import (
    get_file_for_writing,
    get_nomarr_tags,
    release_file_claim,
    resolve_library_root,
    save_mood_tags,
    save_mood_tags_batch,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) for write tests."""
    return Library(name="Test Library", root_path="/music")


class TestGetFileForWriting:
    """Tests for ``get_file_for_writing()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_integer_handle_to_song(self) -> None:
        mock_db = MagicMock()
        identity = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")
        song = MagicMock()
        mock_db.library.resolve_song_identity.return_value = identity
        mock_db.library.get_song.return_value = song

        result = get_file_for_writing(mock_db, "123")

        assert result == (123, "123", song)
        mock_db.library.resolve_song_identity.assert_called_once_with(123)
        mock_db.library.get_song.assert_called_once_with(identity)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_handle_no_longer_resolves(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None

        result = get_file_for_writing(mock_db, "999")

        assert result == (999, "999", None)
        mock_db.library.resolve_song_identity.assert_called_once_with(999)
        mock_db.library.get_song.assert_not_called()


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
            result = get_nomarr_tags(mock_db, 123)

        assert result is returned_tags
        mock_get_song_tags.assert_called_once_with(mock_db, 123, nomarr_only=True)


class TestSaveMoodTags:
    """Tests for ``save_mood_tags()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_writes_three_tiers_always(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")
        mood_tags = Tags(items=(Tag(name="mood-strict", values=("happy",)),))

        with patch("nomarr.components.processing.file_write_comp.set_song_tags") as mock_set_song_tags:
            result = save_mood_tags(mock_db, song, mood_tags)

        assert result == 1
        mock_set_song_tags.assert_has_calls(
            [
                call(mock_db, song, "nom:mood-strict", ["happy"]),
                call(mock_db, song, "nom:mood-regular", []),
                call(mock_db, song, "nom:mood-loose", []),
            ]
        )
        assert mock_set_song_tags.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_nonempty_tiers(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")
        mood_tags = Tags(
            items=(
                Tag(name="nom:mood-strict", values=("happy",)),
                Tag(name="mood-regular", values=("calm", "warm")),
            )
        )

        with patch("nomarr.components.processing.file_write_comp.set_song_tags"):
            result = save_mood_tags(mock_db, song, mood_tags)

        assert result == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_clears_absent_tiers_with_empty_list(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")
        mood_tags = Tags(items=(Tag(name="nom:mood-loose", values=("chill",)),))

        with patch("nomarr.components.processing.file_write_comp.set_song_tags") as mock_set_song_tags:
            save_mood_tags(mock_db, song, mood_tags)

        mock_set_song_tags.assert_any_call(mock_db, song, "nom:mood-strict", [])
        mock_set_song_tags.assert_any_call(mock_db, song, "nom:mood-regular", [])
        mock_set_song_tags.assert_any_call(mock_db, song, "nom:mood-loose", ["chill"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_none_clears_all_three_tiers(self) -> None:
        """The strict None state clears every mood tier with an empty value list."""
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")

        with patch("nomarr.components.processing.file_write_comp.set_song_tags") as mock_set_song_tags:
            result = save_mood_tags(mock_db, song, None)

        assert result == 0
        mock_set_song_tags.assert_has_calls(
            [
                call(mock_db, song, "nom:mood-strict", []),
                call(mock_db, song, "nom:mood-regular", []),
                call(mock_db, song, "nom:mood-loose", []),
            ]
        )
        assert mock_set_song_tags.call_count == 3


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
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")
        mood_tags = Tags(items=(Tag(name="mood-strict", values=("happy",)),))
        items: list[tuple[SongIdentity, Tags | None]] = [(song, mood_tags)]

        with patch(
            "nomarr.components.processing.file_write_comp.set_song_tags_batch",
        ) as mock_set_song_tags_batch:
            result = save_mood_tags_batch(mock_db, items)

        assert result == 1
        mock_set_song_tags_batch.assert_called_once_with(
            mock_db,
            [
                {
                    "song": song,
                    "name": "nom:mood-strict",
                    "values": ["happy"],
                },
                {"song": song, "name": "nom:mood-regular", "values": []},
                {"song": song, "name": "nom:mood-loose", "values": []},
            ],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_none_entry_clears_all_three_tiers(self) -> None:
        """A None mood_tags entry emits empty value lists for every tier."""
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "file-1.flac")
        items: list[tuple[SongIdentity, Tags | None]] = [(song, None)]

        with patch(
            "nomarr.components.processing.file_write_comp.set_song_tags_batch",
        ) as mock_set_song_tags_batch:
            result = save_mood_tags_batch(mock_db, items)

        assert result == 0
        mock_set_song_tags_batch.assert_called_once_with(
            mock_db,
            [
                {"song": song, "name": "nom:mood-strict", "values": []},
                {"song": song, "name": "nom:mood-regular", "values": []},
                {"song": song, "name": "nom:mood-loose", "values": []},
            ],
        )


class TestReleaseFileClaim:
    """Tests for ``release_file_claim()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_release_claim(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")
        mock_db.library.resolve_song_identity.return_value = song

        with patch("nomarr.components.processing.file_write_comp.release_claim") as mock_release_claim:
            release_file_claim(mock_db, "123", "worker:write:0")

        mock_release_claim.assert_called_once_with(mock_db, song, "worker:write:0")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_exceptions(self) -> None:
        mock_db = MagicMock()
        song = SongIdentity(LibraryIdentity("library-1", "Music", "/music"), "song.flac")
        mock_db.library.resolve_song_identity.return_value = song

        with patch(
            "nomarr.components.processing.file_write_comp.release_claim",
            side_effect=RuntimeError("boom"),
        ) as mock_release_claim:
            release_file_claim(mock_db, "123", "worker:write:0")

        mock_release_claim.assert_called_once_with(mock_db, song, "worker:write:0")
