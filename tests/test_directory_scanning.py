"""
Test directory scanning functionality for queue endpoints.
Ensures that paths can be files or directories, and directories are recursively scanned.
"""

import pytest

from nomarr.helpers.files import collect_audio_files


@pytest.mark.unit
class TestDirectoryScanning:
    """Test collect_audio_files helper."""

    def test_single_file(self, tmp_path):
        """Test scanning a single audio file."""
        # Create test file
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        # Scan the file
        files = collect_audio_files(str(test_file))

        assert len(files) == 1
        assert files[0] == str(test_file.resolve())

    def test_non_audio_file(self, tmp_path):
        """Test scanning a non-audio file returns empty list."""
        from nomarr.helpers.files import collect_audio_files

        # Create non-audio file
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"not audio")

        # Scan the file
        files = collect_audio_files(str(test_file))

        assert len(files) == 0

    def test_directory_recursive(self, tmp_path):
        """Test recursively scanning a directory for audio files."""
        from nomarr.helpers.files import collect_audio_files

        # Create directory structure with audio files
        (tmp_path / "subdir1").mkdir()
        (tmp_path / "subdir2").mkdir()
        (tmp_path / "subdir1" / "nested").mkdir()

        # Create audio files at different levels
        files_created = [
            tmp_path / "root.mp3",
            tmp_path / "subdir1" / "track1.flac",
            tmp_path / "subdir1" / "nested" / "track2.ogg",
            tmp_path / "subdir2" / "track3.m4a",
        ]

        for f in files_created:
            f.write_bytes(b"fake audio")

        # Create non-audio files (should be ignored)
        (tmp_path / "readme.txt").write_bytes(b"not audio")
        (tmp_path / "subdir1" / "cover.jpg").write_bytes(b"image")

        # Scan the directory recursively
        files = collect_audio_files(str(tmp_path), recursive=True)

        assert len(files) == 4
        # Verify all created audio files were found
        for created in files_created:
            assert str(created.resolve()) in files

    def test_directory_non_recursive(self, tmp_path):
        """Test non-recursive directory scanning (only top level)."""
        from nomarr.helpers.files import collect_audio_files

        # Create directory structure
        (tmp_path / "subdir").mkdir()

        # Create audio files at different levels
        root_file = tmp_path / "root.mp3"
        nested_file = tmp_path / "subdir" / "nested.mp3"

        root_file.write_bytes(b"fake audio")
        nested_file.write_bytes(b"fake audio")

        # Scan non-recursively
        files = collect_audio_files(str(tmp_path), recursive=False)

        assert len(files) == 1
        assert str(root_file.resolve()) in files
        assert str(nested_file.resolve()) not in files

    def test_empty_directory(self, tmp_path):
        """Test scanning empty directory returns empty list."""
        from nomarr.helpers.files import collect_audio_files

        files = collect_audio_files(str(tmp_path))

        assert len(files) == 0

    def test_nonexistent_path(self):
        """Test scanning non-existent path returns empty list."""
        from nomarr.helpers.files import collect_audio_files

        files = collect_audio_files("/nonexistent/path")

        assert len(files) == 0

    def test_multiple_extensions(self, tmp_path):
        """Test scanning finds all supported audio extensions."""
        from nomarr.helpers.files import AUDIO_EXTENSIONS, collect_audio_files

        # Create file for each extension
        for ext in AUDIO_EXTENSIONS:
            test_file = tmp_path / f"test{ext}"
            test_file.write_bytes(b"fake audio")

        # Scan directory
        files = collect_audio_files(str(tmp_path))

        assert len(files) == len(AUDIO_EXTENSIONS)

    def test_deduplication(self, tmp_path):
        """Test that duplicate paths are removed (edge case)."""
        from nomarr.helpers.files import collect_audio_files

        # This is mainly to verify the set() deduplication works
        # In practice, duplicates shouldn't occur, but the function handles it
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        files = collect_audio_files(str(test_file))

        # Should only get one result even though we're scanning a file
        assert len(files) == 1


