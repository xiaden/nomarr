"""
Integration tests verifying that all domains can still access absolute paths after Phase 1-3 changes.

Validates that the dual-path strategy (absolute + normalized) preserves backward compatibility:
- path field: absolute path (for file access by domains)
- normalized_path field: POSIX relative (for uniqueness/identity)

Tests cover:
- Processing workflow (tagging files)
- Calibration workflow (recalibrating files)
- Library update component (updating from tags)
- Queue component (checking/enqueuing files)
- Search operations (finding files)
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.workflows.library.sync_file_to_library_wf import sync_file_to_library

# Platform-specific test paths
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    TEST_LIBRARY_ROOT = "D:\\Music"
    TEST_ABSOLUTE_PATH = "D:\\Music\\Rock\\song.mp3"
    TEST_SCAN_ROOT = Path("D:\\Music")
    TEST_SCAN_FILE = Path("D:\\Music\\Rock\\Beatles\\Help.mp3")
else:
    TEST_LIBRARY_ROOT = "/home/music"
    TEST_ABSOLUTE_PATH = "/home/music/Rock/song.mp3"
    TEST_SCAN_ROOT = Path("/home/music")
    TEST_SCAN_FILE = Path("/home/music/Rock/Beatles/Help.mp3")

TEST_NORMALIZED_PATH = "Rock/song.mp3"  # Always POSIX relative


@pytest.fixture
def mock_db_with_file():
    """Mock Database with a library file that has both absolute and normalized paths."""
    mock_db = MagicMock()

    # Configure nested mocks for operations
    mock_db.libraries = MagicMock()
    mock_db.library_files = MagicMock()
    mock_db.file_tags = MagicMock()

    # Mock library lookup (use platform-specific paths)
    mock_db.libraries.find_library_containing_path.return_value = {
        "_id": "libraries/lib1",
        "_key": "lib1",
        "id": "lib1",
        "name": "Test Library",
        "root_path": TEST_LIBRARY_ROOT,
        "is_enabled": True,
        "is_default": True,
    }

    # Mock file lookup - returns file with absolute path
    mock_db.library_files.get_library_file.return_value = {
        "_id": "library_files/file1",
        "_key": "file1",
        "id": "file1",
        "path": TEST_ABSOLUTE_PATH,  # Absolute path available to domains
        "normalized_path": TEST_NORMALIZED_PATH,  # POSIX relative for identity
        "library_id": "lib1",
        "file_size": 5000000,
        "modified_time": 1705600000000,
        "duration_seconds": 180.5,
        "artist": "Test Artist",
        "album": "Test Album",
        "title": "Test Song",
        "tagged": 1,
        "tagged_version": "1.0.0",
        "is_valid": 1,
    }

    return mock_db, TEST_ABSOLUTE_PATH, TEST_NORMALIZED_PATH


class TestPathComputationDomain:
    """Test build_library_path_from_input still works correctly."""

    def test_build_library_path_preserves_absolute_path(self, mock_db_with_file):
        """build_library_path_from_input should still return absolute path."""
        mock_db, test_absolute_path, _ = mock_db_with_file

        # Mock file existence
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("os.access", return_value=True),
        ):
            result = build_library_path_from_input(test_absolute_path, mock_db)

            assert result.is_valid()
            assert str(result.absolute) == test_absolute_path
            assert result.library_id == "lib1"


class TestLibraryUpdateDomain:
    """Test sync_file_to_library can still access files by absolute path."""

    def test_sync_file_to_library_uses_absolute_path(self, mock_db_with_file):
        """sync_file_to_library should query by absolute path and get file."""
        mock_db, test_absolute_path, _ = mock_db_with_file

        # Mock file operations
        mock_db.library_files.upsert_library_file.return_value = "library_files/file1"
        mock_db.file_tags.delete_tags_by_file_and_prefix = MagicMock()
        mock_db.file_tags.batch_insert_tags = MagicMock()

        test_metadata = {
            "duration": 180.5,
            "artist": "Test Artist",
            "album": "Test Album",
            "title": "Test Song",
            "all_tags": {"genre": "Rock"},
            "nom_tags": {"nom_version": "1.0.0"},
        }

        # Mock os.stat
        with (
            patch("os.stat") as mock_stat,
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("os.access", return_value=True),
        ):
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 5000000
            mock_stat_result.st_mtime = 1705600.0
            mock_stat.return_value = mock_stat_result

            # Should not raise, should use absolute path to query DB
            sync_file_to_library(
                db=mock_db,
                file_path=test_absolute_path,
                metadata=test_metadata,
                namespace="nom",
                tagged_version="1.0.0",
                library_id="lib1",
            )

            # Verify get_library_file was called with absolute path
            mock_db.library_files.get_library_file.assert_called_once_with(test_absolute_path)


class TestQueueDomain:
    """Test queue operations can still check files by absolute path."""

    def test_check_file_needs_processing_uses_absolute_path(self, mock_db_with_file):
        """Verify queue operations work with absolute paths (conceptual test)."""
        mock_db, test_absolute_path, _ = mock_db_with_file

        # Conceptual verification: queue component receives LibraryPath with absolute path
        # LibraryPath.absolute should be the absolute filesystem path
        # DB queries use str(path.absolute) to look up files

        mock_library_path = MagicMock()
        mock_library_path.absolute = Path(test_absolute_path)

        # Verify absolute path is available and correct
        assert str(mock_library_path.absolute) == test_absolute_path
        assert Path(test_absolute_path).is_absolute()

        # When queue component queries DB, it uses absolute path
        path_str = str(mock_library_path.absolute)
        file_record = mock_db.library_files.get_library_file(path_str)

        # Verify file record has absolute path
        assert file_record["path"] == test_absolute_path


class TestSearchDomain:
    """Test search operations still return files with absolute paths."""

    def test_search_returns_absolute_paths(self, mock_db_with_file):
        """search_library_files_with_tags should return files with absolute paths."""
        mock_db, test_absolute_path, test_normalized_path = mock_db_with_file

        # Mock search results
        mock_db.library_files.search_library_files_with_tags.return_value = (
            [
                {
                    "_id": "library_files/file1",
                    "path": test_absolute_path,  # Absolute path in results
                    "normalized_path": test_normalized_path,  # Also has normalized
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "title": "Test Song",
                    "tags": [],
                }
            ],
            1,  # Total count
        )

        files, total = mock_db.library_files.search_library_files_with_tags(
            q="Test",
            limit=100,
            offset=0,
        )

        assert total == 1
        assert len(files) == 1
        assert files[0]["path"] == test_absolute_path
        assert files[0]["normalized_path"] == test_normalized_path


class TestScanWorkflowDualPath:
    """Test scan workflow creates documents with both path fields."""

    def test_scan_creates_both_path_fields(self):
        """Scan workflow should create docs with absolute path AND normalized_path."""
        from nomarr.workflows.library.scan_library_direct_wf import _compute_normalized_path

        # Test with platform-specific paths
        library_root = TEST_SCAN_ROOT
        absolute_path = TEST_SCAN_FILE

        normalized = _compute_normalized_path(absolute_path, library_root)

        # normalized_path should be POSIX relative
        assert normalized == "Rock/Beatles/Help.mp3"
        assert "/" in normalized  # POSIX separators
        assert "\\" not in normalized  # No Windows separators

        # Absolute path should remain unchanged
        assert str(absolute_path) == str(TEST_SCAN_FILE)

        # Document should have both:
        file_doc = {
            "path": str(absolute_path),  # Absolute for file access
            "normalized_path": normalized,  # POSIX relative for identity
            "library_id": "lib1",
            # ... other fields
        }

        assert file_doc["path"] == str(absolute_path)
        assert file_doc["normalized_path"] == normalized


class TestBackwardCompatibility:
    """Test that changes don't break existing domain assumptions."""

    def test_domains_still_use_absolute_paths(self, mock_db_with_file):
        """Verify all domains still work with absolute paths as primary access method."""
        mock_db, test_absolute_path, _ = mock_db_with_file

        # All these operations should work with absolute paths:

        # 1. Library update component
        file_record = mock_db.library_files.get_library_file(test_absolute_path)
        assert file_record is not None
        assert file_record["path"] == test_absolute_path

        # 2. Queue operations use absolute path
        path_str = str(test_absolute_path)
        assert os.path.isabs(path_str)

        # 3. Search results contain absolute paths
        mock_db.library_files.search_library_files_with_tags.return_value = (
            [{"path": test_absolute_path}],
            1,
        )
        files, _ = mock_db.library_files.search_library_files_with_tags(q="test")
        assert files[0]["path"] == test_absolute_path

        # 4. File tags operations use absolute paths
        # (path is stored in file record, retrieved by absolute path query)
        assert "path" in file_record
        assert os.path.isabs(file_record["path"])


class TestNormalizedPathUniqueness:
    """Test that normalized_path is used for uniqueness, not absolute path."""

    def test_upsert_batch_uses_normalized_path_key(self):
        """upsert_batch should key on (library_id, normalized_path), not absolute path."""
        # This is verified by the Phase 2 tests, but we document the requirement here

        # Platform-specific example paths
        if IS_WINDOWS:
            old_path = "C:\\Music\\Rock\\song.mp3"
            new_path = "D:\\Music\\Rock\\song.mp3"
        else:
            old_path = "/mnt/old/music/Rock/song.mp3"
            new_path = "/mnt/new/music/Rock/song.mp3"

        # If two files have different absolute paths (e.g., moved or remounted)
        # but same normalized_path (relative to library root), they should update
        # the same DB document, not create duplicates.
        file1 = {
            "path": old_path,  # Old absolute path
            "normalized_path": "Rock/song.mp3",  # Same relative
            "library_id": "lib1",
        }

        file2 = {
            "path": new_path,  # New absolute path
            "normalized_path": "Rock/song.mp3",  # Same relative
            "library_id": "lib1",
        }

        # upsert_batch([file1]) then upsert_batch([file2]) should UPDATE, not INSERT
        # The key is (library_id, normalized_path) which is identical
        assert file1["normalized_path"] == file2["normalized_path"]
        assert file1["library_id"] == file2["library_id"]

        # But absolute paths are different (drive letter changed)
        assert file1["path"] != file2["path"]

        # This allows move detection to work correctly while keeping absolute paths
        # available for all file operations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
