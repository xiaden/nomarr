"""Unit tests for the ``Song`` ADR-041 domain dataclass and its row mapping."""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.song_dataclass import Song


def _row(**overrides: object) -> dict:
    base: dict = {
        "id": 10,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/a.mp3",
        "normalized_path": "a.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": 120.5,
        "chromaprint": None,
        "needs_tagging": 1,
        "is_valid": 1,
        "tagged": 1,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": 1000,
        "created_at": 1000,
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_song_from_row_maps_storage_id_to_song_id() -> None:
    song = Song.from_row(_row())

    assert isinstance(song, Song)
    assert song.song_id == 10
    assert song.path == "/music/a.mp3"
    assert song.normalized_path == "a.mp3"
    assert song.file_size == 100
    assert song.needs_tagging is True
    assert song.is_valid is True
    assert song.tagged is True
    assert song.duration_seconds == 120.5


@pytest.mark.unit
def test_song_is_frozen_and_slots() -> None:
    song = Song.from_row(_row())

    # frozen dataclass → cannot reassign fields
    with pytest.raises(AttributeError):
        song.path = "/other.mp3"  # type: ignore[misc]
    # slots dataclass → no __dict__
    assert not hasattr(song, "__dict__")


@pytest.mark.unit
def test_song_to_dict_round_trips_to_storage_shape() -> None:
    row = _row()
    song = Song.from_row(row)

    as_dict = song.to_dict()

    # Storage-facing key is ``id`` (transitional alias for song_id)
    assert as_dict["id"] == 10
    assert as_dict == row


@pytest.mark.unit
def test_song_from_row_nullable_fields() -> None:
    song = Song.from_row(_row(duration_seconds=None, chromaprint=None, scanned_at=None, last_tagged_at=None))

    assert song.duration_seconds is None
    assert song.chromaprint is None
    assert song.scanned_at is None
    assert song.last_tagged_at is None
