"""Characterization tests for LibraryDb facade methods.

Captures the behavior of 15 priority facade methods as JSON snapshots.
These tests establish a baseline of current behavior that future refactors
must preserve.

Each test:
1. Calls a facade method with seed data
2. Serializes the result (with DB ID masking, float rounding, etc.)
3. Compares against a stored snapshot (or creates baseline on first run)

Marked with @pytest.mark.characterization.
"""

from __future__ import annotations

import pytest

from .conftest import assert_snapshot_matches


@pytest.mark.characterization
class TestLibraryDbFacadeCharacterization:
    """Characterization tests for LibraryDb facade methods."""

    def test_add_library(self, db, seed_data):
        """Snapshot: add_library(payload) → int (library ID)."""
        result = db.library.add_library(
            {
                "name": "CharTestLib",
                "path": "/tmp/chartest",
                "library_type": "music",
            }
        )
        assert_snapshot_matches("LibraryDb_add_library", result)
        # Cleanup
        db.library.remove_library(result)

    def test_get_library(self, db, seed_data):
        """Snapshot: get_library(library_id) → LibraryRow | None."""
        lib_id = seed_data["libraries"][0]
        result = db.library.get_library(lib_id)
        assert_snapshot_matches("LibraryDb_get_library", result)

    def test_list_libraries(self, db, seed_data):
        """Snapshot: list_libraries(enabled_only=False) → list[LibraryRow]."""
        result = db.library.list_libraries()
        assert_snapshot_matches("LibraryDb_list_libraries", result)

    def test_add_file_to_library(self, db, seed_data):
        """Snapshot: add_file_to_library(library_id, payload) → int (file ID)."""
        lib_id = seed_data["libraries"][0]
        from nomarr.helpers.time_helper import now_ms

        now_ms_val = now_ms()
        result = db.library.add_file_to_library(
            lib_id,
            {
                "path": "/tmp/chartest/char_song.flac",
                "normalized_path": "/tmp/chartest/char_song.flac",
                "file_size": 999999,
                "modified_time": now_ms_val.value,
                "duration_seconds": 123.456,
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 0,
            },
        )
        assert_snapshot_matches("LibraryDb_add_file_to_library", result)
        # Cleanup: remove the file
        db.library.remove_file(result)

    def test_get_file_by_path(self, db, seed_data):
        """Snapshot: get_file_by_path(path, library_id) → LibraryFileRow | None."""
        # Get the file to find its path
        # We need to query by path, so we'll use a known path from seed_data
        # Since we don't have the path stored, we'll construct it
        lib_id = seed_data["libraries"][0]
        result = db.library.get_file_by_path("/tmp/test1/song1.flac", lib_id)
        assert_snapshot_matches("LibraryDb_get_file_by_path", result)

    def test_list_files_by_ids(self, db, seed_data):
        """Snapshot: list_files_by_ids(file_ids) → list[LibraryFileRow]."""
        file_ids = seed_data["files"][:2]  # First 2 files
        result = db.library.list_files_by_ids(file_ids)
        assert_snapshot_matches("LibraryDb_list_files_by_ids", result)

    def test_replace_file_tags(self, db, seed_data):
        """Snapshot: replace_file_tags(file_id, tags) → None.

        This method returns None, so we snapshot the state after the call
        by reading back the tags.
        """
        file_id = seed_data["files"][0]
        tag_ids = seed_data["tags"][:2]

        # Replace tags
        db.library.replace_file_tags(
            file_id,
            [
                {"tag_id": tag_ids[0], "confidence": 0.99, "source": "test"},
                {"tag_id": tag_ids[1], "confidence": 0.85, "source": "test"},
            ],
        )

        # Read back to snapshot the result
        result = db.library.list_tags_for_file(file_id)
        assert_snapshot_matches("LibraryDb_replace_file_tags", result)

    def test_list_tags_for_file(self, db, seed_data):
        """Snapshot: list_tags_for_file(file_id) → list[TagRow]."""
        file_id = seed_data["files"][0]
        result = db.library.list_tags_for_file(file_id)
        assert_snapshot_matches("LibraryDb_list_tags_for_file", result)

    def test_find_or_create_tag(self, db, seed_data):
        """Snapshot: find_or_create_tag(name, value, namespace) → int (tag ID)."""
        result = db.library.find_or_create_tag("nom:char-test", "charvalue", "nom")
        assert_snapshot_matches("LibraryDb_find_or_create_tag", result)
        # Note: tag persists; cleanup is handled by _cleanup_seed_data

    def test_get_tag(self, db, seed_data):
        """Snapshot: get_tag(tag_id) → TagRow | None."""
        tag_id = seed_data["tags"][0]
        result = db.library.get_tag(tag_id)
        assert_snapshot_matches("LibraryDb_get_tag", result)

    def test_maintenance_delete_tags_by_ids(self, db, seed_data):
        """Snapshot: maintenance.delete_tags_by_ids(tag_ids) → int (deleted count).

        This test creates temporary tags to delete, so we don't affect seed data.
        """
        # Create temporary tags to delete
        temp_tag1 = db.library.find_or_create_tag("temp:delete1", "val1", "temp")
        temp_tag2 = db.library.find_or_create_tag("temp:delete2", "val2", "temp")

        result = db.library.maintenance.delete_tags_by_ids([temp_tag1, temp_tag2])
        assert_snapshot_matches("LibraryDb_maintenance_delete_tags_by_ids", result)

    def test_add_scan(self, db, seed_data):
        """Snapshot: add_scan(library_id, payload) → int (scan ID)."""
        lib_id = seed_data["libraries"][0]
        from nomarr.helpers.time_helper import now_ms

        now_ms_val = now_ms()
        result = db.library.add_scan(
            lib_id,
            {
                "scan_type": "incremental",
                "status": "running",
                "started_at": now_ms_val.value,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            },
        )
        assert_snapshot_matches("LibraryDb_add_scan", result)
        # Cleanup
        db.library.remove_scan(lib_id)

    def test_get_scan(self, db, seed_data):
        """Snapshot: get_scan(library_id) → LibraryScanRow | None."""
        lib_id = seed_data["libraries"][0]
        # seed_data creates a scan for lib_id 0
        result = db.library.get_scan(lib_id)
        assert_snapshot_matches("LibraryDb_get_scan", result)

    def test_update_scan(self, db, seed_data):
        """Snapshot: update_scan(library_id, fields) → None.

        This method returns None, so we snapshot the state after the call
        by reading back the scan.
        """
        lib_id = seed_data["libraries"][0]
        # Update the scan created by seed_data
        db.library.update_scan(
            lib_id,
            {
                "status": "completed",
                "files_processed": 99,
            },
        )
        # Read back to snapshot
        result = db.library.get_scan(lib_id)
        assert_snapshot_matches("LibraryDb_update_scan", result)

    def test_remove_scan(self, db, seed_data):
        """Snapshot: remove_scan(library_id) → None.

        This method returns None, so we verify by checking the scan is gone.
        """
        lib_id = seed_data["libraries"][0]
        # Remove the scan
        db.library.remove_scan(lib_id)
        # Verify it's gone
        result = db.library.get_scan(lib_id)
        assert_snapshot_matches("LibraryDb_remove_scan", result)
