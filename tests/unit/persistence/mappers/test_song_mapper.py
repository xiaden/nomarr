"""Contract tests for the persistence-private song row mappers.

``TASK-song-row-mirror-leaks-into-domain-B`` Phase 1 (P1-S2/P1-S3): prove that
``nomarr/persistence/mappers/song_mapper.py`` converts persistence ``SongRow``
mappings to a semantic application :class:`Song` and to the natural
:class:`SongIdentity` locator, and that generated row ids / foreign keys /
storage serialization never cross the persistence boundary. Row fixtures appear
only in persistence mapper tests (CONTRACTS §2).
"""

from __future__ import annotations

from typing import Any

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.persistence.mappers.song_mapper import (
    song_row_to_domain,
    song_row_to_identity,
)


def _song_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
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
    row.update(overrides)
    return row


@pytest.mark.unit
class TestSongRowToDomain:
    def test_maps_semantic_fields_and_drops_generated_ids(self) -> None:
        song = song_row_to_domain(_song_row())
        assert isinstance(song, Song)
        assert not isinstance(song, dict)
        # Generated row id / FK ints stay persistence-private.
        assert not hasattr(song, "song_id")
        assert not hasattr(song, "id")
        assert not hasattr(song, "library_id")
        assert not hasattr(song, "folder_id")
        # Physical path and library-relative locator path are both preserved.
        assert song.path == "/music/a.mp3"
        assert song.normalized_path == "a.mp3"
        # Integer booleans are coerced to bool.
        assert song.needs_tagging is True
        assert song.is_valid is True
        assert song.tagged is True

    def test_preserves_nullable_values_and_false_booleans(self) -> None:
        song = song_row_to_domain(
            _song_row(
                folder_id=5,
                duration_seconds=None,
                chromaprint="fingerprint",
                needs_tagging=0,
                is_valid=0,
                tagged=0,
                write_claimed_by="worker-1",
                last_tagged_at=2000,
            )
        )
        assert song.folder_id is None  # folder FK never surfaces
        assert song.duration_seconds is None
        assert song.chromaprint == "fingerprint"
        assert song.needs_tagging is False
        assert song.is_valid is False
        assert song.tagged is False
        assert song.write_claimed_by == "worker-1"
        assert song.last_tagged_at == 2000

    def test_preserves_integer_millisecond_timestamps(self) -> None:
        song = song_row_to_domain(_song_row())
        assert song.modified_time == 1000
        assert song.scanned_at == 1000
        assert song.created_at == 1000
        assert isinstance(song.modified_time, int)

    def test_value_has_no_storage_constructor_or_serializer(self) -> None:
        song = song_row_to_domain(_song_row())
        assert not hasattr(song, "from_row")
        assert not hasattr(song, "to_dict")


@pytest.mark.unit
class TestSongRowToIdentity:
    _LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")

    def test_builds_locator_from_library_scoped_row(self) -> None:
        identity = song_row_to_identity(_song_row(library_name="TestLib", root_path="/music"))
        assert isinstance(identity, SongIdentity)
        assert identity.library == self._LIBRARY
        assert identity.normalized_path == "a.mp3"

    def test_root_path_optional(self) -> None:
        identity = song_row_to_identity(_song_row(library_name="TestLib"))
        assert identity.library == LibraryIdentity(name="TestLib")
        assert identity.normalized_path == "a.mp3"

    def test_bare_song_row_without_library_natural_key_raises(self) -> None:
        # A raw SongRow carries only the private library_id; it cannot form a
        # SongIdentity. Failure is deterministic and leak-free.
        with pytest.raises(ValueError, match="library natural identity"):
            song_row_to_identity(_song_row())

    def test_blank_normalized_path_raises(self) -> None:
        with pytest.raises(ValueError, match="normalized_path"):
            song_row_to_identity(_song_row(normalized_path="  ", library_name="TestLib"))
