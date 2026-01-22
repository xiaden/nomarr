"""
Unit tests for scan_library_direct_workflow Phase 2 behavioral invariants.

Tests verify:
1. normalized_path computation (POSIX relpath, no library root prefix, no leading slash)
2. mark_missing_for_library called ONLY for full scans

Uses real test fixtures instead of mocks for more reliable testing.
"""

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto import ScanTarget
from nomarr.workflows.library.scan_library_direct_wf import (
    _compute_normalized_path,
    scan_library_direct_workflow,
)


class TestNormalizedPathInvariant:
    """Test normalized_path computation invariants using real fixtures."""

    def test_compute_normalized_path_posix_output(self, good_library_root):
        """Windows backslashes converted to POSIX forward slashes."""
        # Setup: Use real fixture path
        library_root = good_library_root.resolve()
        file_path = (good_library_root / "Rock" / "Beatles" / "help.mp3").resolve()

        # Execute
        result = _compute_normalized_path(file_path, library_root)

        # Assert: POSIX format (forward slashes)
        assert result == "Rock/Beatles/help.mp3"
        assert "\\" not in result

    def test_compute_normalized_path_no_leading_slash(self, good_library_root):
        """normalized_path never starts with '/'."""
        library_root = good_library_root.resolve()
        file_path = (good_library_root / "Jazz" / "Miles" / "so_what.flac").resolve()

        result = _compute_normalized_path(file_path, library_root)

        assert not result.startswith("/")
        assert result == "Jazz/Miles/so_what.flac"

    def test_compute_normalized_path_no_library_root_prefix(self, good_library_root):
        """normalized_path does not contain library root name."""
        library_root = good_library_root.resolve()
        file_path = (good_library_root / "Classical" / "Bach" / "fugue.flac").resolve()

        result = _compute_normalized_path(file_path, library_root)

        # Should not contain parent directory names (only relative path)
        assert "fixtures" not in result
        assert "library" not in result
        assert "good" not in result
        assert result == "Classical/Bach/fugue.flac"

    def test_compute_normalized_path_raises_on_outside_root(self, good_library_root, bad_library_root):
        """Raises ValueError if file is outside library root."""
        library_root = good_library_root.resolve()
        file_path = (bad_library_root / "Invalid").resolve()

        with pytest.raises(ValueError):
            _compute_normalized_path(file_path, library_root)


class TestFullScanMissingMarkInvariant:
    """Test mark_missing_for_library called ONLY for full scans using real fixtures."""

    def test_full_scan_calls_mark_missing(self, good_library_root):
        """Full scan (folder_path='') calls mark_missing_for_library."""
        # Setup: Mock only database calls
        db = MagicMock()
        library_root_str = str(good_library_root.resolve())
        db.libraries.get_library.return_value = {
            "_id": "lib1",
            "root_path": library_root_str,
        }
        # Return empty tuple for list_library_files (not get_library_files!)
        db.library_files.list_library_files.return_value = ([], 0)
        db.library_files.mark_missing_for_library.return_value = 0

        # Execute: Full scan (real filesystem walk will happen)
        scan_targets = [ScanTarget(library_id="lib1", folder_path="")]
        scan_library_direct_workflow(db, "lib1", scan_targets, tagger_version="test123")

        # Assert: mark_missing_for_library was called
        db.library_files.mark_missing_for_library.assert_called_once()
        call_args = db.library_files.mark_missing_for_library.call_args
        assert call_args[0][0] == "lib1"  # library_id
        assert isinstance(call_args[0][1], str)  # scan_id

    def test_targeted_scan_does_not_call_mark_missing(self, good_library_root):
        """Targeted scan (folder_path='Some/Subdir') does NOT call mark_missing_for_library."""
        # Setup: Mock only database calls
        db = MagicMock()
        library_root_str = str(good_library_root.resolve())
        db.libraries.get_library.return_value = {
            "_id": "lib1",
            "root_path": library_root_str,
        }
        db.library_files.list_library_files.return_value = ([], 0)

        # Execute: Targeted scan (real filesystem walk will happen)
        scan_targets = [ScanTarget(library_id="lib1", folder_path="Rock/Beatles")]
        scan_library_direct_workflow(db, "lib1", scan_targets, tagger_version="test123")

        # Assert: mark_missing_for_library was NOT called
        db.library_files.mark_missing_for_library.assert_not_called()

    def test_multiple_targets_does_not_call_mark_missing(self, good_library_root):
        """Multiple scan targets does NOT call mark_missing_for_library."""
        # Setup: Mock only database calls
        db = MagicMock()
        library_root_str = str(good_library_root.resolve())
        db.libraries.get_library.return_value = {
            "_id": "lib1",
            "root_path": library_root_str,
        }
        db.library_files.list_library_files.return_value = ([], 0)

        # Execute: Multiple targets (real filesystem walk will happen)
        scan_targets = [
            ScanTarget(library_id="lib1", folder_path="Rock"),
            ScanTarget(library_id="lib1", folder_path="Jazz"),
        ]
        scan_library_direct_workflow(db, "lib1", scan_targets, tagger_version="test123")

        # Assert: mark_missing_for_library was NOT called
        db.library_files.mark_missing_for_library.assert_not_called()


class TestUpsertBatchUsesNormalizedPath:
    """Test upsert_batch receives normalized_path using real fixtures."""

    def test_upsert_batch_receives_normalized_path(self, good_library_root):
        """upsert_batch called with normalized_path field (POSIX relative)."""
        # Setup: Mock only database calls
        db = MagicMock()
        library_root = good_library_root.resolve()
        library_root_str = str(library_root)

        db.libraries.get_library.return_value = {
            "_id": "lib1",
            "root_path": library_root_str,
        }
        # Mock find_library_containing_path (called by build_library_path_from_input)
        db.libraries.find_library_containing_path.return_value = {
            "_id": "lib1",
            "root_path": library_root_str,
        }
        # Return empty tuple for list_library_files
        db.library_files.list_library_files.return_value = ([], 0)
        db.library_files.mark_missing_for_library.return_value = 0

        # Execute: Full scan with batch_size=100 (force end-of-folder flushes, not mid-folder)
        scan_targets = [ScanTarget(library_id="lib1", folder_path="")]
        result = scan_library_direct_workflow(db, "lib1", scan_targets, tagger_version="test123", batch_size=100)

        # Debug: Check result to understand what happened
        print(f"\nScan result: {result}")
        print(f"Warnings: {result.get('warnings', [])}")
        print(f"Files discovered: {result.get('files_discovered', 0)}")
        print(f"Files added: {result.get('files_added', 0)}")
        print(f"Files failed: {result.get('files_failed', 0)}")

        # Assert: upsert_batch or batch_upsert_library_files called with normalized_path
        assert db.library_files.upsert_batch.called or db.library_files.batch_upsert_library_files.called, (
            f"Neither upsert method was called. Result: {result}"
        )

        # Get the call_args - look for non-empty batch (skip final flush of empty batch)
        if db.library_files.upsert_batch.called:
            # Find first non-empty batch call
            non_empty_calls = [call for call in db.library_files.upsert_batch.call_args_list if len(call[0][0]) > 0]
            assert len(non_empty_calls) > 0, (
                f"All upsert_batch calls had empty batches. Call list: {db.library_files.upsert_batch.call_args_list}, Result: {result}"
            )
            call_args = non_empty_calls[0][0][0]
        else:
            # Find first non-empty batch call
            non_empty_calls = [
                call for call in db.library_files.batch_upsert_library_files.call_args_list if len(call[0][0]) > 0
            ]
            assert len(non_empty_calls) > 0, f"All batch_upsert_library_files calls had empty batches. Result: {result}"
            call_args = non_empty_calls[0][0][0]

        # Verify normalized_path field exists and is POSIX relative
        assert len(call_args) > 0
        file_doc = call_args[0]
        assert "normalized_path" in file_doc, "File document missing normalized_path field"
        assert "path" in file_doc, "File document missing path field"

        normalized = file_doc["normalized_path"]
        absolute = file_doc["path"]

        # Invariant 1: normalized_path is relative (no drive letter, no absolute markers)
        assert not normalized.startswith("/"), "normalized_path should not start with /"
        assert ":" not in normalized, "normalized_path should not contain drive letter"
        assert "\\" not in normalized, "normalized_path should use POSIX format (forward slashes)"

        # Invariant 2: normalized_path does not contain parent directory names
        assert "fixtures" not in normalized, "normalized_path should not contain 'fixtures'"
        assert "library" not in normalized, "normalized_path should not contain 'library'"
        assert "good" not in normalized, "normalized_path should not contain 'good'"

        # Invariant 3: absolute path is different from normalized
        assert normalized != absolute, "normalized_path should differ from absolute path"

        # Invariant 4: normalized_path is relative within library (starts with genre/artist)
        assert "/" in normalized, f"normalized_path should contain path separators: '{normalized}'"
        # Should be something like "Rock/Beatles/help.mp3" or "Jazz/Miles/so_what.flac"
        assert normalized.count("/") >= 2, f"normalized_path should have at least 2 levels: '{normalized}'"
