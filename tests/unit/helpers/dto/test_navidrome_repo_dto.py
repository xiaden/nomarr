"""Unit tests for navidrome_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.navidrome_repo_dto import NdPlayRecord, NdTrackRecord


@pytest.mark.unit
class TestNdTrackRecord:
    """Tests for NdTrackRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """NdTrackRecord should be creatable with all required fields."""
        row = NdTrackRecord(
            id="nd_track_1",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            file_path="/music/test.mp3",
            created_at=1000,
        )
        assert row["id"] == "nd_track_1"
        assert row["title"] == "Test Song"
        assert row["artist"] == "Test Artist"
        assert row["album"] == "Test Album"
        assert row["file_path"] == "/music/test.mp3"
        assert row["created_at"] == 1000


@pytest.mark.unit
class TestNdPlayRecord:
    """Tests for NdPlayRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """NdPlayRecord should be creatable with all required fields."""
        row = NdPlayRecord(
            nd_id="nd_track_1",
            file_id=42,
            playcount=5,
            last_played=2000,
        )
        assert row["nd_id"] == "nd_track_1"
        assert row["file_id"] == 42
        assert row["playcount"] == 5
        assert row["last_played"] == 2000
