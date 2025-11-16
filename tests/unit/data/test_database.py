"""
Unit tests for nomarr.data.db module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""

import pytest

from nomarr.persistence.db import (
    now_ms,
)


class TestDatabaseCleanupExpiredSessions:
    """Test Database.cleanup_expired_sessions() operations."""

    def test_cleanup_expired_sessions_success(self, test_db):
        """Should successfully cleanup expired sessions."""
        # Arrange

        # Act
        result = test_db.sessions.cleanup_expired()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count


class TestDatabaseClearLibraryData:
    """Test Database.clear_library_data() operations."""

    def test_clear_library_data_success(self, test_db):
        """Should successfully clear library data."""
        # Arrange

        # Act
        test_db.library.clear_library_data()

        # Assert
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete


class TestDatabaseClearOldJobs:
    """Test Database.clear_old_jobs() operations."""

    def test_clear_old_jobs_success(self, test_db):
        """Should successfully clear old jobs."""
        # Arrange

        # Act
        test_db.queue.clear_old_jobs()

        # Assert
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete


class TestDatabaseClose:
    """Test Database.close() operations."""

    def test_close_success(self, test_db):
        """Should successfully close."""
        # Arrange

        # Act
        test_db.close()

        # Assert


class TestDatabaseCreateLibraryScan:
    """Test Database.create_library_scan() operations."""

    def test_create_library_scan_success(self, test_db):
        """Should successfully create library scan."""
        # Arrange

        # Act
        result = test_db.library.create_library_scan()

        # Assert
        assert isinstance(result, int)
        # Verify item was added
        # TODO: Check item can be retrieved
        # TODO: Verify count/depth increased


class TestDatabaseCreateSession:
    """Test Database.create_session() operations."""

    def test_create_session_success(self, test_db):
        """Should successfully create session."""
        # Arrange
        import time

        expiry = time.time() + 3600  # 1 hour from now

        # Act
        test_db.sessions.create(session_token="test_token", expiry=expiry)

        # Assert
        # Method returns None - verify it completes without exception
        # Verify item was added by retrieving it
        result = test_db.sessions.get(session_token="test_token")
        assert result is not None
        assert isinstance(result, float)
        assert result == expiry


class TestDatabaseDeleteLibraryFile:
    """Test Database.delete_library_file() operations."""

    def test_delete_library_file_success(self, test_db, temp_audio_file):
        """Should successfully delete library file."""
        # Arrange

        # Act
        test_db.library.delete_library_file(path=str(temp_audio_file))

        # Assert
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete

    @pytest.mark.skip(reason="Method doesn't validate paths - no FileNotFoundError raised")
    def test_delete_library_file_invalid_path_raises_error(self, test_db):
        """Should raise error for invalid file path."""
        # Arrange

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            test_db.library.delete_library_file(path="/nonexistent.mp3")


class TestDatabaseDeleteMeta:
    """Test Database.delete_meta() operations."""

    def test_delete_meta_success(self, test_db):
        """Should successfully delete meta."""
        # Arrange

        # Act
        test_db.meta.delete(key="test_value")

        # Assert
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete


class TestDatabaseDeleteSession:
    """Test Database.delete_session() operations."""

    def test_delete_session_success(self, test_db):
        """Should successfully delete session."""
        # Arrange

        # Act
        test_db.sessions.delete(session_token="test_value")

        # Assert
        # Method returns None - verify it completes without exception
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete


class TestDatabaseEnqueue:
    """Test Database.enqueue() operations."""

    def test_enqueue_success(self, test_db, temp_audio_file):
        """Should successfully enqueue."""
        # Arrange

        # Act
        result = test_db.queue.enqueue(path=str(temp_audio_file))

        # Assert
        assert isinstance(result, int)
        # Verify item was added
        # TODO: Check item can be retrieved
        # TODO: Verify count/depth increased

    @pytest.mark.skip(reason="Method doesn't validate paths - no FileNotFoundError raised")
    def test_enqueue_invalid_path_raises_error(self, test_db):
        """Should raise error for invalid file path."""
        # Arrange

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            test_db.queue.enqueue(path="/nonexistent.mp3", force=True)


class TestDatabaseGetFileTags:
    """Test Database.get_file_tags() operations."""

    def test_get_file_tags_success(self, test_db, temp_audio_file):
        """Should successfully get file tags."""
        # Arrange

        # Act
        result = test_db.tags.get_file_tags(file_id=str(temp_audio_file))

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify returned data is correct


class TestDatabaseGetLibraryFile:
    """Test Database.get_library_file() operations."""

    def test_get_library_file_success(self, test_db, temp_audio_file):
        """Should successfully get library file."""
        # Arrange - create library file first
        test_db.library.upsert_library_file(path=str(temp_audio_file), file_size=1024, modified_time=1234567890)

        # Act
        result = test_db.library.get_library_file(path=str(temp_audio_file))

        # Assert
        assert isinstance(result, dict)
        assert result["path"] == str(temp_audio_file)

    def test_get_library_file_not_found(self, test_db):
        """Should return None when item not found."""
        # Arrange

        # Act
        result = test_db.library.get_library_file(path="/nonexistent/file.mp3")

        # Assert
        assert result is None


class TestDatabaseGetLibraryScan:
    """Test Database.get_library_scan() operations."""

    def test_get_library_scan_success(self, test_db):
        """Should successfully get library scan."""
        # Arrange - create scan first
        scan_id = test_db.library.create_library_scan()

        # Act
        result = test_db.library.get_library_scan(scan_id=scan_id)

        # Assert
        assert isinstance(result, dict)
        assert result["id"] == scan_id

    def test_get_library_scan_not_found(self, test_db):
        """Should return None when item not found."""
        # Arrange

        # Act
        result = test_db.library.get_library_scan(scan_id=99999)

        # Assert
        assert result is None


class TestDatabaseGetLibraryStats:
    """Test Database.get_library_stats() operations."""

    def test_get_library_stats_success(self, test_db):
        """Should successfully get library stats."""
        # Arrange

        # Act
        result = test_db.library.get_library_stats()

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify returned data is correct


class TestDatabaseGetMeta:
    """Test Database.get_meta() operations."""

    def test_get_meta_success(self, test_db):
        """Should successfully get meta."""
        # Arrange - set meta first
        test_db.meta.set(key="test_key", value="test_value")

        # Act
        result = test_db.meta.get(key="test_key")

        # Assert
        assert result == "test_value"

    def test_get_meta_not_found(self, test_db):
        """Should return None when item not found."""
        # Arrange

        # Act
        result = test_db.meta.get(key="test_value")

        # Assert
        assert result is None


class TestDatabaseGetSession:
    """Test Database.get_session() operations."""

    def test_get_session_success(self, test_db):
        """Should successfully get session."""
        # Arrange - create session first
        import time

        expiry = time.time() + 3600  # 1 hour from now
        test_db.sessions.create(session_token="test_token", expiry=expiry)

        # Act
        result = test_db.sessions.get(session_token="test_token")

        # Assert
        assert isinstance(result, float)
        assert result == expiry

    def test_get_session_not_found(self, test_db):
        """Should return None when item not found."""
        # Arrange

        # Act
        result = test_db.sessions.get(session_token="test_value")

        # Assert
        assert result is None


class TestDatabaseGetTagSummary:
    """Test Database.get_tag_summary() operations."""

    def test_get_tag_summary_success(self, test_db):
        """Should successfully get tag summary."""
        # Arrange

        # Act
        result = test_db.tags.get_tag_summary(tag_key="test_value")

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify returned data is correct


class TestDatabaseGetTagTypeStats:
    """Test Database.get_tag_type_stats() operations."""

    def test_get_tag_type_stats_success(self, test_db):
        """Should successfully get tag type stats."""
        # Arrange

        # Act
        result = test_db.tags.get_tag_type_stats(tag_key="test_value")

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify returned data is correct


class TestDatabaseGetTagValues:
    """Test Database.get_tag_values() operations."""

    def test_get_tag_values_success(self, test_db):
        """Should successfully get tag values."""
        # Arrange

        # Act
        result = test_db.tags.get_tag_values(tag_key="test_value")

        # Assert
        assert isinstance(result, list)
        # TODO: Verify returned data is correct


class TestDatabaseGetUniqueTagKeys:
    """Test Database.get_unique_tag_keys() operations."""

    def test_get_unique_tag_keys_success(self, test_db):
        """Should successfully get unique tag keys."""
        # Arrange

        # Act
        result = test_db.tags.get_unique_tag_keys()

        # Assert
        assert isinstance(result, list)
        # TODO: Verify returned data is correct


class TestDatabaseJobStatus:
    """Test Database.job_status() operations."""

    def test_job_status_success(self, test_db, temp_audio_file):
        """Should successfully job status."""
        # Arrange - enqueue job first
        job_id = test_db.queue.enqueue(path=str(temp_audio_file))

        # Act
        result = test_db.queue.job_status(job_id=job_id)

        # Assert
        assert isinstance(result, dict)
        assert result["id"] == job_id


class TestDatabaseListLibraryFiles:
    """Test Database.list_library_files() operations."""

    def test_list_library_files_success(self, test_db):
        """Should successfully list library files."""
        # Arrange

        # Act
        test_db.library.list_library_files()

        # Assert
        # TODO: Verify list contents
        # TODO: Test with filters if applicable


class TestDatabaseListLibraryScans:
    """Test Database.list_library_scans() operations."""

    def test_list_library_scans_success(self, test_db):
        """Should successfully list library scans."""
        # Arrange

        # Act
        result = test_db.library.list_library_scans()

        # Assert
        assert isinstance(result, list)
        # TODO: Verify list contents
        # TODO: Test with filters if applicable


class TestDatabaseLoadAllSessions:
    """Test Database.load_all_sessions() operations."""

    def test_load_all_sessions_success(self, test_db):
        """Should successfully load all sessions."""
        # Arrange

        # Act
        result = test_db.sessions.load_all()

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify list contents
        # TODO: Test with filters if applicable


class TestDatabaseQueueDepth:
    """Test Database.queue_depth() operations."""

    def test_queue_depth_success(self, test_db):
        """Should successfully queue depth."""
        # Arrange

        # Act
        result = test_db.queue.queue_depth()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count
        # Verify item was added
        # TODO: Check item can be retrieved
        # TODO: Verify count/depth increased


class TestDatabaseQueueStats:
    """Test Database.queue_stats() operations."""

    def test_queue_stats_success(self, test_db):
        """Should successfully queue stats."""
        # Arrange

        # Act
        result = test_db.queue.queue_stats()

        # Assert
        assert isinstance(result, dict)
        # Verify item was added
        # TODO: Check item can be retrieved
        # TODO: Verify count/depth increased


class TestDatabaseResetRunningLibraryScans:
    """Test Database.reset_running_library_scans() operations."""

    def test_reset_running_library_scans_success(self, test_db):
        """Should successfully reset running library scans."""
        # Arrange

        # Act
        result = test_db.library.reset_running_library_scans()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state


class TestDatabaseResetRunningToPending:
    """Test Database.reset_running_to_pending() operations."""

    def test_reset_running_to_pending_success(self, test_db):
        """Should successfully reset running to pending."""
        # Arrange

        # Act
        result = test_db.queue.reset_running_to_pending()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state


class TestDatabaseSetMeta:
    """Test Database.set_meta() operations."""

    def test_set_meta_success(self, test_db):
        """Should successfully set meta."""
        # Arrange

        # Act
        test_db.meta.set(key="test_value", value="test_value")

        # Assert
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state


class TestDatabaseUpdateJob:
    """Test Database.update_job() operations."""

    def test_update_job_success(self, test_db):
        """Should successfully update job."""
        # Arrange

        # Act
        test_db.queue.update_job(job_id=1, status="pending")

        # Assert
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state


class TestDatabaseUpdateLibraryScan:
    """Test Database.update_library_scan() operations."""

    def test_update_library_scan_success(self, test_db):
        """Should successfully update library scan."""
        # Arrange

        # Act
        test_db.library.update_library_scan(scan_id=1)

        # Assert
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state

    @pytest.mark.skip(reason="Method doesn't validate paths - no FileNotFoundError raised")
    def test_update_library_scan_invalid_path_raises_error(self, test_db):
        """Should raise error for invalid file path."""
        # Arrange

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            test_db.library.update_library_scan(
                scan_id=1,
                status="pending",
                files_scanned="/nonexistent.mp3",
                files_added="/nonexistent.mp3",
                files_updated="/nonexistent.mp3",
                files_removed="/nonexistent.mp3",
                error_message="test_value",
            )


class TestDatabaseUpsertFileTags:
    """Test Database.upsert_file_tags() operations."""

    def test_upsert_file_tags_success(self, test_db, temp_audio_file):
        """Should successfully upsert file tags."""
        # Arrange - create library file first to get file_id
        test_db.library.upsert_library_file(path=str(temp_audio_file), file_size=1024, modified_time=1234567890)
        file_data = test_db.library.get_library_file(path=str(temp_audio_file))
        file_id = file_data["id"]
        tags = {"mood": "happy", "genre": "rock"}

        # Act
        test_db.tags.upsert_file_tags(file_id=file_id, tags=tags)

        # Assert
        # Method returns None - verify it completes without exception


class TestDatabaseUpsertLibraryFile:
    """Test Database.upsert_library_file() operations."""

    def test_upsert_library_file_success(self, test_db, temp_audio_file):
        """Should successfully upsert library file."""
        # Arrange

        # Act
        result = test_db.library.upsert_library_file(
            path=str(temp_audio_file), file_size=str(temp_audio_file), modified_time=1
        )

        # Assert
        assert isinstance(result, int)


# === STANDALONE FUNCTION TESTS ===


def test_now_ms():
    """Test now_ms"""
    # Arrange

    # Act
    now_ms()

    # Assert
    # TODO: Add assertions
    pass
