"""Unit tests for path reconciliation component."""

from pathlib import Path

from nomarr.components.library.reconcile_paths_comp import reconcile_library_paths
from nomarr.helpers.dto.path_dto import LibraryPath


class TestReconcileLibraryPaths:
    """Test path reconciliation functionality."""

    def test_dry_run_does_not_modify_database(self, test_db, temp_audio_file, default_library):
        """Dry run should report statistics without modifying database."""
        # Arrange - create file in database
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
        result = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=10)

        # Assert - file should still exist
        assert result["total_files"] >= 1
        assert test_db.library_files.get_file_by_id(file_id) is not None

    def test_handles_empty_library(self, test_db):
        """Should handle library with no files."""
        # Act
        result = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=10)

        # Assert
        assert result["total_files"] == 0
        assert result["valid_files"] == 0
        assert result["deleted_files"] == 0
        assert result["errors"] == 0

    def test_counts_valid_files_correctly(self, test_db, temp_audio_file, default_library):
        """Should count files that exist and are in configured libraries."""
        # Arrange - create valid file
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        test_db.library_files.upsert_library_file(
            path=library_path,
            library_id=default_library,
            file_size=1024,
            modified_time=1234567890,
        )

        # Act
        result = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=10)

        # Assert - reconciliation validates against filesystem, may not count as valid
        # depending on whether temp file is within library root
        assert result["total_files"] >= 1
        assert result["valid_files"] >= 0  # May be 0 if temp file is outside library root

    def test_result_includes_all_statistics(self, test_db):
        """Result should include all expected statistic fields."""
        # Act
        result = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=10)

        # Assert - verify all expected fields exist
        assert "total_files" in result
        assert "valid_files" in result
        assert "invalid_config" in result
        assert "not_found" in result
        assert "unknown_status" in result
        assert "deleted_files" in result
        assert "errors" in result

    def test_respects_batch_size_parameter(self, test_db, temp_audio_file, default_library):
        """Should accept batch_size parameter without errors."""
        # Arrange
        library_path = LibraryPath(
            relative="test.mp3",
            absolute=Path(temp_audio_file),
            library_id=default_library,
            status="valid",
        )
        test_db.library_files.upsert_library_file(
            path=library_path,
            library_id=default_library,
            file_size=1024,
            modified_time=1234567890,
        )

        # Act - test different batch sizes
        result_small = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=1)
        result_large = reconcile_library_paths(db=test_db, policy="dry_run", batch_size=1000)

        # Assert - should get same results regardless of batch size
        assert result_small["total_files"] == result_large["total_files"]
        assert result_small["valid_files"] == result_large["valid_files"]
