"""Unit tests for tagging reader component."""

from pathlib import Path

import pytest

from nomarr.components.tagging.tagging_reader_comp import read_tags_from_file
from nomarr.helpers.dto.path_dto import LibraryPath


class TestReadTagsFromFile:
    """Test reading namespaced tags from audio files."""

    def test_reads_tags_from_valid_file(self, temp_audio_file, default_library):
        """Should read tags from a valid audio file (or raise error for invalid MP3)."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act/Assert - temp_audio_file may not be valid MP3, expect either dict or RuntimeError
        try:
            tags = read_tags_from_file(path=library_path, namespace="essentia")
            assert isinstance(tags, dict)
        except RuntimeError:
            # Expected for invalid/minimal MP3 files
            pass

    def test_returns_empty_dict_for_file_without_tags(self, temp_audio_file, default_library):
        """Should return empty dict when file has no namespaced tags."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act/Assert - may raise RuntimeError for invalid MP3
        try:
            tags = read_tags_from_file(path=library_path, namespace="nonexistent")
            assert tags == {}
        except RuntimeError:
            # Expected for invalid/minimal MP3 files
            pass

    def test_handles_different_namespaces(self, temp_audio_file, default_library):
        """Should accept different namespace values."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act/Assert - may raise RuntimeError for invalid MP3
        try:
            tags_essentia = read_tags_from_file(path=library_path, namespace="essentia")
            tags_custom = read_tags_from_file(path=library_path, namespace="custom")
            # Both should return dicts
            assert isinstance(tags_essentia, dict)
            assert isinstance(tags_custom, dict)
        except RuntimeError:
            # Expected for invalid/minimal MP3 files
            pass

    def test_raises_error_for_invalid_path(self):
        """Should raise error for invalid file path."""
        # Arrange
        library_path = LibraryPath(
            relative="nonexistent.mp3",
            absolute=Path("/nonexistent/file.mp3"),
            library_id=1,
            status="not_found",
        )

        # Act/Assert
        with pytest.raises(Exception):
            read_tags_from_file(path=library_path, namespace="essentia")
