"""
Unit tests for nomarr.services.queue module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""

import pytest


class TestQueueServiceAddFiles:
    """Test QueueService.add_files() operations."""

    def test_add_files_success(self, real_queue_service, temp_audio_file):
        """Should successfully add files."""
        # Arrange

        # Act
        result = real_queue_service.add_files(paths=[str(temp_audio_file)])

        # Assert
        assert isinstance(result, dict)
        # Verify item was added
        # TODO: Check item can be retrieved
        # TODO: Verify count/depth increased

    def test_add_files_invalid_path_raises_error(self, real_queue_service):
        """Should raise error for invalid file path."""
        # Arrange

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            real_queue_service.add_files(paths=["/nonexistent.mp3"], force=True, recursive=True)


class TestQueueServiceCleanupOldJobs:
    """Test QueueService.cleanup_old_jobs() operations."""

    def test_cleanup_old_jobs_success(self, real_queue_service):
        """Should successfully cleanup old jobs."""
        # Arrange

        # Act
        result = real_queue_service.cleanup_old_jobs()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count


class TestQueueServiceGetStatus:
    """Test QueueService.get_status() operations."""

    def test_get_status_success(self, real_queue_service):
        """Should successfully get queue status with depth and counts."""
        # Arrange

        # Act
        result = real_queue_service.get_status()

        # Assert
        from nomarr.services.queue_svc import QueueStatus

        assert isinstance(result, QueueStatus)
        assert isinstance(result.depth, int)
        assert result.depth >= 0  # Non-negative count
        assert isinstance(result.counts, dict)


class TestQueueServiceGetJob:
    """Test QueueService.get_job() operations."""

    def test_get_job_success(self, real_queue_service, temp_audio_file):
        """Should successfully get job."""
        # Arrange - add a job first
        add_result = real_queue_service.add_files(paths=[str(temp_audio_file)])
        job_id = add_result["job_ids"][0]  # Get first job ID from list

        # Act
        result = real_queue_service.get_job(job_id=job_id)

        # Assert
        from nomarr.helpers.dto.queue_dto import JobDict

        assert isinstance(result, JobDict)
        assert result.id == job_id
        assert result.status is not None
        assert result.path is not None

    def test_get_job_not_found(self, real_queue_service):
        """Should return None when item not found."""
        # Arrange

        # Act
        result = real_queue_service.get_job(job_id=99999)

        # Assert
        assert result is None


class TestQueueServiceListJobs:
    """Test QueueService.publish_queue_update() operations."""

    def test_publish_queue_update_success(self, real_queue_service):
        """Should successfully publish queue update."""
        # Arrange

        # Act
        real_queue_service.publish_queue_update(event_broker=None)

        # Assert
        # Method returns None - verify it completes without exception


class TestQueueServiceRemoveJobs:
    """Test QueueService.remove_jobs() operations."""

    def test_remove_jobs_success(self, real_queue_service):
        """Should successfully remove jobs."""
        # Arrange

        # Act
        result = real_queue_service.remove_jobs(all=True)

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count
        # TODO: Verify item was removed
        # TODO: Verify get() returns None after delete


class TestQueueServiceResetJobs:
    """Test QueueService.reset_jobs() operations."""

    def test_reset_jobs_success(self, real_queue_service):
        """Should successfully reset jobs."""
        # Arrange

        # Act
        result = real_queue_service.reset_jobs(stuck=True)

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count
        # TODO: Verify state changed
        # TODO: Verify get() reflects new state
        pass
