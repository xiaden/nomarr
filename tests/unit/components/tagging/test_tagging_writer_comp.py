"""Unit tests for tagging writer component."""

from pathlib import Path

import pytest

from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dto.path_dto import LibraryPath


class TestTagWriter:
    """Test TagWriter class for writing tags to audio files."""

    def test_creates_writer_with_defaults(self):
        """Should create TagWriter with default parameters."""
        # Act
        writer = TagWriter()

        # Assert - should not raise exception
        assert writer is not None

    def test_creates_writer_with_custom_namespace(self):
        """Should create TagWriter with custom namespace."""
        # Act
        writer = TagWriter(namespace="custom")

        # Assert
        assert writer is not None

    def test_creates_writer_with_overwrite_disabled(self):
        """Should create TagWriter with overwrite disabled."""
        # Act
        writer = TagWriter(overwrite=False)

        # Assert
        assert writer is not None

    def test_writes_tags_to_valid_file(self, temp_audio_file, default_library):
        """Should write tags to a valid audio file."""
        # Arrange
        writer = TagWriter(namespace="essentia")
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        tags = {"mood-happy": "0.8", "genre": "rock"}

        # Act - should not raise exception
        writer.write(path=library_path, tags=tags)

        # Assert - write completes without error (returns None)

    def test_writes_empty_tags_dict(self, temp_audio_file, default_library):
        """Should handle writing empty tags dict."""
        # Arrange
        writer = TagWriter(namespace="essentia")
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        tags: dict[str, str] = {}

        # Act - should not raise exception
        writer.write(path=library_path, tags=tags)

        # Assert - write completes without error

    def test_writes_various_tag_types(self, temp_audio_file, default_library):
        """Should handle different tag value types."""
        # Arrange
        writer = TagWriter(namespace="essentia")
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        tags = {
            "mood-happy": 0.8,  # float
            "count": 5,  # int
            "genre": "rock",  # string
        }

        # Act - should not raise exception
        writer.write(path=library_path, tags=tags)

        # Assert - write completes without error

    def test_raises_error_for_invalid_path(self):
        """Should raise error for invalid file path."""
        # Arrange
        writer = TagWriter(namespace="essentia")
        library_path = LibraryPath(
            relative="nonexistent.mp3",
            absolute=Path("/nonexistent/file.mp3"),
            library_id=1,
            status="not_found",
        )
        tags = {"mood-happy": "0.8"}

        # Act/Assert
        with pytest.raises(Exception):
            writer.write(path=library_path, tags=tags)
