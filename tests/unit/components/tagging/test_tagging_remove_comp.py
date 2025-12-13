"""Unit tests for tagging remove component."""

from pathlib import Path

import pytest

from nomarr.components.tagging.tagging_remove_comp import remove_tags_from_file
from nomarr.helpers.dto.path_dto import LibraryPath


class TestRemoveTagsFromFile:
    """Test removing namespaced tags from audio files."""

    def test_removes_tags_from_valid_file(self, temp_audio_file, default_library):
        """Should remove tags from a valid audio file."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act
        count = remove_tags_from_file(path=library_path, namespace="essentia")

        # Assert - should return number of tags removed (may be 0)
        assert isinstance(count, int)
        assert count >= 0

    def test_returns_zero_when_no_tags_exist(self, temp_audio_file, default_library):
        """Should return 0 when file has no namespaced tags."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act
        count = remove_tags_from_file(path=library_path, namespace="nonexistent")

        # Assert
        assert count == 0

    def test_handles_different_namespaces(self, temp_audio_file, default_library):
        """Should accept different namespace values."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )

        # Act - try different namespaces
        count_essentia = remove_tags_from_file(path=library_path, namespace="essentia")
        count_custom = remove_tags_from_file(path=library_path, namespace="custom")

        # Assert - both should return int
        assert isinstance(count_essentia, int)
        assert isinstance(count_custom, int)

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
            remove_tags_from_file(path=library_path, namespace="essentia")
