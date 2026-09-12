"""Tests for nomarr.components.library.song_sync_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_sync_comp import mark_song_processed, save_song_tags
from nomarr.components.playlist_import.track_matcher_comp import LibraryTrack
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity


def _song(normalized_path: str = "song.flac") -> SongIdentity:
    """Semantic locator used to address a song at the component boundary."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="691ebf37-b1e4-5244-a9c0-4758c39eaab6", name="Test Library"),
        normalized_path=normalized_path,
    )


class TestMarkFileTagged:
    """Tests for mark_song_processed delegation."""

    @pytest.mark.unit
    @patch("nomarr.components.library.song_sync_comp.persist_last_tagged_at")
    @patch("nomarr.components.library.song_sync_comp.transition_song_state")
    def test_delegates_to_state_transition_and_timestamp_update(
        self,
        mock_transition_file_state: MagicMock,
        mock_persist_last_tagged_at: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        song = _song()

        mark_song_processed(mock_db, song)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [song],
            STATE_NOT_PROCESSED,
            STATE_PROCESSED,
        )
        mock_persist_last_tagged_at.assert_called_once_with(mock_db, song)


class TestSaveSongTags:
    """Tests for save_song_tags delegation to set_song_tags_batch."""

    @pytest.mark.unit
    @patch("nomarr.components.library.song_sync_comp.set_song_tags_batch")
    def test_delegates_one_entry_per_parsed_name_to_batch_write(
        self,
        mock_set_song_tags_batch: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        song = _song()
        parsed_tags = {
            "genre": ["classical", "baroque"],
            "nom:mood": ["calm"],
        }

        save_song_tags(mock_db, song, parsed_tags)

        mock_set_song_tags_batch.assert_called_once_with(
            mock_db,
            [
                {"song": song, "name": "genre", "values": ["classical", "baroque"]},
                {"song": song, "name": "nom:mood", "values": ["calm"]},
            ],
        )

    @pytest.mark.unit
    @patch("nomarr.components.library.song_sync_comp.set_song_tags_batch")
    def test_forwards_empty_entries_when_no_tags_parsed(
        self,
        mock_set_song_tags_batch: MagicMock,
    ) -> None:
        # Production forwards to set_song_tags_batch unconditionally; the batch
        # helper itself is the empty-guard, so we assert a single call with the
        # empty entry list rather than no call (matches actual save_song_tags).
        mock_db = MagicMock()

        save_song_tags(mock_db, _song(), {})

        mock_set_song_tags_batch.assert_called_once_with(mock_db, [])

    @pytest.mark.unit
    @patch("nomarr.components.library.song_sync_comp.set_song_tags_batch")
    def test_propagates_semantic_locator_into_batch_payload(
        self,
        mock_set_song_tags_batch: MagicMock,
    ) -> None:
        # Regression: save_song_tags addresses the song by its semantic
        # SongIdentity locator — the integer storage id never enters the payload.
        mock_db = MagicMock()
        song = _song()

        save_song_tags(mock_db, song, {"genre": ["classical"]})

        payload = mock_set_song_tags_batch.call_args.args[1]
        assert len(payload) == 1
        assert payload[0]["song"] == song
        assert isinstance(payload[0]["song"], SongIdentity)
        assert "song_id" not in payload[0]


class TestLibraryTrackFromDbRow:
    """Tests for LibraryTrack.from_db_row row-to-DTO conversion."""

    @pytest.mark.unit
    def test_requires_id_key_instead_of_silent_empty_fallback(self) -> None:
        # Regression: from_db_row reads row["id"] directly; a row without the
        # id key must raise KeyError rather than silently yielding file_id="".
        with pytest.raises(KeyError):
            LibraryTrack.from_db_row({"path": "/music/song.flac"})

    @pytest.mark.unit
    def test_accepts_integer_id(self) -> None:
        track = LibraryTrack.from_db_row({"id": 42, "path": "/music/song.flac"})
        assert track.file_id == 42
        assert isinstance(track.file_id, int)
