"""Unit tests for tag cleanup component."""

from pathlib import Path

from nomarr.components.library.tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count
from nomarr.helpers.dto.path_dto import LibraryPath


class TestGetOrphanedTagCount:
    """Test counting orphaned tags."""

    def test_counts_orphaned_tags(self, test_db):
        """Should count tags not linked to any files."""
        # Arrange - create tags without linking them
        test_db.library_tags.get_or_create_tag(key="genre", value="rock", is_nomarr_tag=False)
        test_db.library_tags.get_or_create_tag(key="mood-strict", value="happy", is_nomarr_tag=True)

        # Act
        count = get_orphaned_tag_count(db=test_db)

        # Assert
        assert count == 2

    def test_excludes_linked_tags(self, test_db, temp_audio_file, default_library):
        """Should not count tags that are linked to files."""
        # Arrange - create file and use upsert_file_tags to link
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

        # Link one tag via upsert_file_tags
        test_db.file_tags.upsert_file_tags(file_id=file_id, tags={"genre": "rock"}, is_nomarr_tag=False)

        # Create an orphaned tag
        test_db.library_tags.get_or_create_tag(key="mood", value="happy", is_nomarr_tag=True)

        # Act
        count = get_orphaned_tag_count(db=test_db)

        # Assert
        assert count == 1  # Only the orphaned tag should be counted


class TestCleanupOrphanedTags:
    """Test deleting orphaned tags."""

    def test_deletes_orphaned_tags(self, test_db):
        """Should delete tags not linked to any files."""
        # Arrange - create orphaned tags
        test_db.library_tags.get_or_create_tag(key="genre", value="rock", is_nomarr_tag=False)
        test_db.library_tags.get_or_create_tag(key="mood-strict", value="happy", is_nomarr_tag=True)

        # Act
        deleted_count = cleanup_orphaned_tags(db=test_db)

        # Assert
        assert deleted_count == 2
        assert get_orphaned_tag_count(db=test_db) == 0

    def test_preserves_linked_tags(self, test_db, temp_audio_file, default_library):
        """Should not delete tags linked to files."""
        # Arrange - create file with linked tag
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

        # Link tag via upsert_file_tags
        test_db.file_tags.upsert_file_tags(file_id=file_id, tags={"genre": "rock"}, is_nomarr_tag=False)

        # Create orphaned tag
        test_db.library_tags.get_or_create_tag(key="mood", value="happy", is_nomarr_tag=True)

        # Act
        deleted_count = cleanup_orphaned_tags(db=test_db)

        # Assert
        assert deleted_count == 1  # Only orphaned tag deleted

    def test_handles_empty_tag_table(self, test_db):
        """Should handle empty tag table without errors."""
        # Act
        deleted_count = cleanup_orphaned_tags(db=test_db)

        # Assert
        assert deleted_count == 0

    def test_counts_match_between_count_and_cleanup(self, test_db):
        """Count and cleanup should report same number."""
        # Arrange - create orphaned tags
        test_db.library_tags.get_or_create_tag(key="genre", value="rock", is_nomarr_tag=False)
        test_db.library_tags.get_or_create_tag(key="mood", value="happy", is_nomarr_tag=True)

        # Act
        count_before = get_orphaned_tag_count(db=test_db)
        deleted_count = cleanup_orphaned_tags(db=test_db)

        # Assert
        assert count_before == deleted_count
        assert get_orphaned_tag_count(db=test_db) == 0
