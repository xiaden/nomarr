"""Unit tests for file tags component."""

from pathlib import Path

from nomarr.components.library.file_tags_comp import get_file_tags_with_path
from nomarr.helpers.dto.path_dto import LibraryPath


class TestGetFileTagsWithPath:
    """Test file tag retrieval functionality."""

    def test_returns_tags_for_existing_file(self, test_db, temp_audio_file, default_library):
        """Should return file path and tags for an existing file."""
        # Arrange - create file with tags
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        file_id = test_db.library_files.upsert_library_file(
            path=library_path,
            library_id=default_library,
            file_size=1024,
            modified_time=1234567890,
        )

        # Add tags using upsert_file_tags
        tags = {"genre": "rock", "mood-strict": "happy"}
        test_db.file_tags.upsert_file_tags(file_id=file_id, tags=tags, is_nomarr_tag=True)

        # Act
        result = get_file_tags_with_path(db=test_db, file_id=file_id, nomarr_only=False)

        # Assert
        assert result is not None
        assert result["path"] == str(temp_audio_file)
        assert len(result["tags"]) >= 2

    def test_filters_nomarr_tags_only(self, test_db, temp_audio_file, default_library):
        """Should filter to only Nomarr tags when nomarr_only=True."""
        # Arrange - create file with mixed tags
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        file_id = test_db.library_files.upsert_library_file(
            path=library_path,
            library_id=default_library,
            file_size=1024,
            modified_time=1234567890,
        )

        # Add user tags and nomarr tags
        external_tags = {"favorite": "true"}
        nomarr_tags = {"mood-strict": "happy"}
        test_db.file_tags.upsert_file_tags_mixed(file_id=file_id, external_tags=external_tags, nomarr_tags=nomarr_tags)

        # Act
        result = get_file_tags_with_path(db=test_db, file_id=file_id, nomarr_only=True)

        # Assert
        assert result is not None
        # Should only have nomarr tags
        for tag in result["tags"]:
            assert tag["is_nomarr_tag"] is True

    def test_returns_none_for_nonexistent_file(self, test_db):
        """Should return None for file that doesn't exist."""
        # Act
        result = get_file_tags_with_path(db=test_db, file_id=99999, nomarr_only=False)

        # Assert
        assert result is None

    def test_returns_empty_tags_for_file_without_tags(self, test_db, temp_audio_file, default_library):
        """Should return empty tags list for file with no tags."""
        # Arrange - create file without tags
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        file_id = test_db.library_files.upsert_library_file(
            path=library_path,
            library_id=default_library,
            file_size=1024,
            modified_time=1234567890,
        )

        # Act
        result = get_file_tags_with_path(db=test_db, file_id=file_id, nomarr_only=False)

        # Assert
        assert result is not None
        assert result["tags"] == []
