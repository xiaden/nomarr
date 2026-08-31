"""Characterization tests for LibraryDb facade methods (domain contracts).

Phase 6 of ``TASK-song-intent-facade-correction-A``: these tests were rewritten
from the legacy int-id/raw-row facade shapes to the sealed domain contracts
(ADR-032/041/043):

- Libraries are ``Library`` domain values (``create_library`` / ``get_library`` /
  ``update_library`` / ``remove_library``), never storage ``library_id``.
- Songs are addressed by ``SongIdentity`` natural key (resolved from storage ids
  only through the identity bridge ``resolve_song_identity``).
- Tags are ``TagRef`` natural keys (``ensure_tag`` / ``get_tag``), never
  integer tag ids.
- Tag writes use ``SongTagAssignment`` domain values; reads return typed domain
  values (``SongTagAssignment``, ``TagUsage``, ``TagCleanupResult``).
- Scan lifecycle is ``start_scan`` / ``record_scan_progress`` / ``complete_scan`` /
  ``get_scan`` / ``remove_scan`` over ``Library`` natural identity.

These tests require a live PostgreSQL container (``requires_database`` /
``characterization``); in environments without Docker they are recorded as
UNAVAILABLE-PostgreSQL, not failures.

Each test:
1. Calls a facade method with seed data
2. Serializes the result (with DB ID masking, float rounding, etc.)
3. Compares against a stored snapshot (or creates baseline on first run)

Marked with @pytest.mark.characterization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryUpdate
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef

from .conftest import assert_snapshot_matches

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


def _lib1(seed_data: dict) -> Library:
    return cast("Library", seed_data["libraries"][0])


def _song_identity(db, song_id: int) -> SongIdentity:
    identity = db.library.resolve_song_identity(song_id)
    assert identity is not None
    return cast(SongIdentity, identity)


@pytest.mark.characterization
@pytest.mark.requires_database
class TestLibraryDbFacadeCharacterization:
    """Characterization tests for LibraryDb facade methods."""

    def test_create_library(self, db, seed_data):
        """Snapshot: create_library(Library) → Library (domain value)."""
        result = db.library.create_library(Library(name="CharTestLib", root_path="/tmp/chartest"))
        assert_snapshot_matches("LibraryDb_create_library", result)
        # Cleanup
        db.library.remove_library(result)

    def test_get_library(self, db, seed_data):
        """Snapshot: get_library(Library) → Library | None."""
        result = db.library.get_library(_lib1(seed_data))
        assert_snapshot_matches("LibraryDb_get_library", result)

    def test_list_libraries(self, db, seed_data):
        """Snapshot: list_libraries(enabled_only=False) → list[Library]."""
        result = db.library.list_libraries()
        assert_snapshot_matches("LibraryDb_list_libraries", result)

    def test_update_library(self, db, seed_data):
        """Snapshot: update_library(Library, LibraryUpdate) → Library."""
        result = db.library.update_library(_lib1(seed_data), LibraryUpdate(name="RenamedLib"))
        assert_snapshot_matches("LibraryDb_update_library", result)

    def test_add_song_to_library(self, db, seed_data):
        """Snapshot: add_song_to_library(Library, payload) → int (song id)."""
        from nomarr.helpers.time_helper import now_ms

        now_ms_val = now_ms()
        result = db.library.add_song_to_library(
            _lib1(seed_data),
            {
                "path": "/tmp/test1/char_song.flac",
                "normalized_path": "/tmp/test1/char_song.flac",
                "file_size": 999999,
                "modified_time": now_ms_val.value,
                "duration_seconds": 123.456,
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 0,
            },
        )
        assert_snapshot_matches("LibraryDb_add_song_to_library", result)
        # Cleanup: remove the song
        db.library.remove_song(result)

    def test_get_song_by_path(self, db, seed_data):
        """Snapshot: get_song_by_path(path, Library) → Song | None."""
        result = db.library.get_song_by_path("/tmp/test1/song1.flac", _lib1(seed_data))
        assert_snapshot_matches("LibraryDb_get_song_by_path", result)

    def test_list_songs_by_ids(self, db, seed_data):
        """Snapshot: list_songs_by_ids(song_ids) → list[Song]."""
        song_ids = seed_data["songs"][:2]  # First 2 songs (storage ids)
        result = db.library.list_songs_by_ids(song_ids)
        assert_snapshot_matches("LibraryDb_list_songs_by_ids", result)

    def test_replace_song_tags(self, db, seed_data):
        """Snapshot: replace_song_tags(SongIdentity, Sequence[SongTagAssignment]) → None.

        This method returns None, so we snapshot the state after the call
        by reading back the tags as domain assignments.
        """
        song = _song_identity(db, seed_data["songs"][0])
        from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment

        # Replace tags with two domain assignments
        db.library.replace_song_tags(
            song,
            [
                SongTagAssignment(
                    name="nom:mood-strict", value="happy", namespace="nom", confidence=0.99, source="test"
                ),
                SongTagAssignment(name="nom:genre", value="rock", namespace="nom", confidence=0.85, source="test"),
            ],
        )

        # Read back to snapshot the result (typed domain assignments)
        result = db.library.list_tags_for_song(song)
        assert_snapshot_matches("LibraryDb_replace_song_tags", result)

    def test_list_tags_for_song(self, db, seed_data):
        """Snapshot: list_tags_for_song(SongIdentity) → tuple[SongTagAssignment, ...]."""
        song = _song_identity(db, seed_data["songs"][0])
        result = db.library.list_tags_for_song(song)
        assert_snapshot_matches("LibraryDb_list_tags_for_song", result)

    def test_ensure_tag(self, db, seed_data):
        """Snapshot: ensure_tag(TagRef) → TagRef (domain natural key)."""
        result = db.library.ensure_tag(TagRef(name="nom:char-test", value="charvalue", namespace="nom"))
        assert_snapshot_matches("LibraryDb_ensure_tag", result)
        # Note: tag persists; cleanup is handled by _cleanup_seed_data

    def test_get_tag(self, db, seed_data):
        """Snapshot: get_tag(TagRef) → TagRef | None."""
        identity = TagRef(name="nom:genre", value="rock", namespace="nom")
        db.library.ensure_tag(identity)
        result = db.library.get_tag(identity)
        assert_snapshot_matches("LibraryDb_get_tag", result)

    def test_maintenance_cleanup_orphaned_tags(self, db, seed_data):
        """Snapshot: cleanup_orphaned_tags() → TagCleanupResult.

        This test creates a temporary tag without a song assignment so the
        cleanup reports it as discovered (and, with a live orphan, deleted).
        """
        db.library.ensure_tag(TagRef(name="temp:delete1", value="val1", namespace="temp"))
        db.library.ensure_tag(TagRef(name="temp:delete2", value="val2", namespace="temp"))

        result = db.library.admin_cleanup_orphaned_tags()
        assert_snapshot_matches("LibraryDb_maintenance_cleanup_orphaned_tags", result)

    def test_start_scan(self, db, seed_data):
        """Snapshot: start_scan(Library, scan_type, started_at) → LibraryScan."""
        from nomarr.helpers.time_helper import now_ms

        now_ms_val = now_ms()
        result = db.library.start_scan(seed_data["libraries"][1], scan_type="incremental", started_at=now_ms_val.value)
        assert_snapshot_matches("LibraryDb_start_scan", result)
        # Cleanup
        db.library.remove_scan(seed_data["libraries"][1])

    def test_get_scan(self, db, seed_data):
        """Snapshot: get_scan(Library) → LibraryScan | None."""
        result = db.library.get_scan(_lib1(seed_data))
        assert_snapshot_matches("LibraryDb_get_scan", result)

    def test_complete_scan(self, db, seed_data):
        """Snapshot: complete_scan(Library, finished_at) → LibraryScan.

        This method returns the resulting LibraryScan, which we snapshot.
        """
        from nomarr.helpers.time_helper import now_ms

        now_ms_val = now_ms()
        db.library.start_scan(seed_data["libraries"][1], scan_type="incremental", started_at=now_ms_val.value)
        result = db.library.complete_scan(seed_data["libraries"][1], finished_at=now_ms_val.value + 1000)
        assert_snapshot_matches("LibraryDb_complete_scan", result)

    def test_remove_scan(self, db, seed_data):
        """Snapshot: remove_scan(Library) → None.

        This method returns None, so we verify by checking the scan is gone.
        """
        result = db.library.remove_scan(_lib1(seed_data))
        # Read back to snapshot the absence
        scan = db.library.get_scan(_lib1(seed_data))
        assert_snapshot_matches("LibraryDb_remove_scan", scan)
        assert result is None
