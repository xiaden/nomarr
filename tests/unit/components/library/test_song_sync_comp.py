"""Tests for nomarr.components.library.song_sync_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import TrackSong
from nomarr.components.library.song_sync_comp import mark_song_processed, save_song_tags
from nomarr.components.playlist_import.track_matcher_comp import LibraryTrack
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song


def _song(normalized_path: str = "song.flac") -> SongIdentity:
    """Semantic locator used to address a song at the component boundary."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="691ebf37-b1e4-5244-a9c0-4758c39eaab6", name="Test Library"),
        normalized_path=normalized_path,
    )


def _semantic_song(normalized_path: str = "song.flac") -> Song:
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=1,
        modified_time=1,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=True,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1,
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


class TestLibraryTrackFromTrackSong:
    """Tests for the typed ``TrackSong`` → ``LibraryTrack`` conversion.

    The converter preserves the semantic ``SongIdentity`` locator and never
    invents a generated integer handle or raw-row field.
    """

    @pytest.mark.unit
    def test_carries_semantic_locator_and_metadata(self) -> None:
        locator = _song("song.flac")
        track = TrackSong(
            song=_semantic_song("song.flac"),
            metadata={"title": "T", "artist": "A", "album": "B"},
            isrc="US1234567890",
        )

        lib_track = LibraryTrack.from_track_song(locator, track)

        assert lib_track.song_identity is locator
        assert lib_track.file_path == "/music/song.flac"
        assert lib_track.title == "T"
        assert lib_track.artist == "A"
        assert lib_track.album == "B"
        assert lib_track.isrc == "US1234567890"
        assert not hasattr(lib_track, "file_id")

    @pytest.mark.unit
    def test_non_string_metadata_is_treated_as_absent(self) -> None:
        locator = _song()
        track = TrackSong(song=_semantic_song(), metadata={"title": 5, "artist": None}, isrc=None)

        lib_track = LibraryTrack.from_track_song(locator, track)

        assert lib_track.title == ""
        assert lib_track.artist == ""
        assert lib_track.album is None
        assert lib_track.isrc is None
