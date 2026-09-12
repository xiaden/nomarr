"""Unit tests for the semantic ``Song`` ADR-041/ADR-048 application value object.

``Song`` carries only application-facing fields; row-to-domain conversion lives
in the persistence mapper (``nomarr.persistence.mappers.song_mapper``). These
tests intentionally carry no row fixture: persistence-private row shapes are
exercised only in the persistence mapper/repository suites.
"""

from __future__ import annotations

import dataclasses

import pytest

from nomarr.helpers.dataclasses.song_dataclass import Song

_SEMANTIC_FIELDS = {
    "path",
    "normalized_path",
    "file_size",
    "modified_time",
    "duration_seconds",
    "chromaprint",
    "needs_tagging",
    "is_valid",
    "tagged",
    "calibration_hash",
    "write_claimed_by",
    "last_tagged_at",
    "scanned_at",
    "created_at",
}


def _song(**overrides: object) -> Song:
    base: dict = {
        "path": "/music/a.mp3",
        "normalized_path": "a.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": 120.5,
        "chromaprint": None,
        "needs_tagging": True,
        "is_valid": True,
        "tagged": True,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": 1000,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


@pytest.mark.unit
def test_song_carries_semantic_fields() -> None:
    song = _song()

    assert isinstance(song, Song)
    assert song.path == "/music/a.mp3"
    assert song.normalized_path == "a.mp3"
    assert song.file_size == 100
    assert song.needs_tagging is True
    assert song.is_valid is True
    assert song.tagged is True
    assert song.duration_seconds == 120.5


@pytest.mark.unit
def test_song_is_frozen_and_slots() -> None:
    song = _song()

    # frozen dataclass → cannot reassign fields
    with pytest.raises(AttributeError):
        song.path = "/other.mp3"  # type: ignore[misc]
    # slots dataclass → no __dict__
    assert not hasattr(song, "__dict__")


@pytest.mark.unit
def test_song_exposes_only_semantic_fields_no_storage_identity_or_row_mapping() -> None:
    """No generated id, storage FK, row alias, ``from_row``, or ``to_dict``."""
    assert {field.name for field in dataclasses.fields(Song)} == _SEMANTIC_FIELDS
    song = _song()
    for forbidden in ("song_id", "id", "library_id", "folder_id", "from_row", "to_dict"):
        assert not hasattr(song, forbidden), f"Song must not expose {forbidden!r}"


@pytest.mark.unit
def test_song_nullable_fields() -> None:
    song = _song(duration_seconds=None, chromaprint=None, scanned_at=None, last_tagged_at=None)

    assert song.duration_seconds is None
    assert song.chromaprint is None
    assert song.scanned_at is None
    assert song.last_tagged_at is None
