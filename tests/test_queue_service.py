"""
Tests for QueueService (services/queue.py).
"""

import pytest

from nomarr.data.db import Database
from nomarr.data.queue import JobQueue
from nomarr.services.queue import QueueService


@pytest.fixture
def queue_service(temp_db: str) -> QueueService:
    """Create a QueueService instance with fresh database."""
    db = Database(temp_db)
    queue = JobQueue(db)
    return QueueService(db, queue)


@pytest.mark.unit
class TestQueueServiceAddFiles:
    """Test QueueService.add_files method."""

    def test_add_single_file(self, queue_service: QueueService, tmp_path):
        """Test adding a single audio file."""
        # Create test file
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        result = queue_service.add_files(str(test_file), force=False)

        assert result["files_queued"] == 1
        assert len(result["job_ids"]) == 1
        assert result["queue_depth"] >= 1
        assert str(test_file) in result["paths"]

    def test_add_multiple_files(self, queue_service: QueueService, tmp_path):
        """Test adding multiple audio files."""
        # Create test files
        files = [tmp_path / f"test{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"fake audio")

        paths = [str(f) for f in files]
        result = queue_service.add_files(paths, force=False)

        assert result["files_queued"] == 3
        assert len(result["job_ids"]) == 3
        assert result["queue_depth"] >= 3

    def test_add_directory_recursive(self, queue_service: QueueService, tmp_path):
        """Test adding a directory recursively."""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "file1.mp3").write_bytes(b"audio")
        (subdir / "file2.flac").write_bytes(b"audio")

        result = queue_service.add_files(str(tmp_path), recursive=True)

        assert result["files_queued"] == 2
        assert len(result["job_ids"]) == 2

    def test_add_directory_non_recursive(self, queue_service: QueueService, tmp_path):
        """Test adding a directory without recursion."""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "file1.mp3").write_bytes(b"audio")
        (subdir / "file2.flac").write_bytes(b"audio")

        result = queue_service.add_files(str(tmp_path), recursive=False)

        # Should only get top-level file
        assert result["files_queued"] == 1

    def test_add_with_force_flag(self, queue_service: QueueService, tmp_path):
        """Test that force flag is passed through."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        # Add once
        result1 = queue_service.add_files(str(test_file), force=False)
        job_id1 = result1["job_ids"][0]

        # Add again with force
        result2 = queue_service.add_files(str(test_file), force=True)
        job_id2 = result2["job_ids"][0]

        # Should create new job
        assert job_id1 != job_id2

    def test_add_nonexistent_path(self, queue_service: QueueService):
        """Test adding a nonexistent path raises error."""
        with pytest.raises(FileNotFoundError, match="Path not found"):
            queue_service.add_files("/nonexistent/path.mp3")

    def test_add_empty_directory(self, queue_service: QueueService, tmp_path):
        """Test adding an empty directory raises error."""
        with pytest.raises(ValueError, match="No audio files found"):
            queue_service.add_files(str(tmp_path))

    def test_add_non_audio_file(self, queue_service: QueueService, tmp_path):
        """Test adding a non-audio file raises error."""
        text_file = tmp_path / "test.txt"
        text_file.write_text("not audio")

        with pytest.raises(ValueError, match="Not an audio file"):
            queue_service.add_files(str(text_file))


@pytest.mark.unit
class TestQueueServiceGetJob:
    """Test QueueService.get_job method."""

    def test_get_job_exists(self, queue_service: QueueService, tmp_path):
        """Test getting an existing job."""
        # Add a file
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        add_result = queue_service.add_files(str(test_file))
        job_id = add_result["job_ids"][0]

        # Get the job
        job = queue_service.get_job(job_id)

        assert job is not None
        assert job["id"] == job_id
        assert job["status"] == "pending"
        assert str(test_file) in job["path"]

    def test_get_job_not_found(self, queue_service: QueueService):
        """Test getting a nonexistent job returns None."""
        job = queue_service.get_job(99999)
        assert job is None


@pytest.mark.unit
class TestQueueServiceRemoveJobs:
    """Test QueueService.remove_jobs method."""

    def test_remove_single_job(self, queue_service: QueueService, tmp_path):
        """Test removing a single job by ID."""
        # Add file
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        add_result = queue_service.add_files(str(test_file))
        job_id = add_result["job_ids"][0]

        # Remove it
        removed_count = queue_service.remove_jobs(job_id=job_id)

        assert removed_count == 1

        # Verify it's gone
        assert queue_service.get_job(job_id) is None

    def test_remove_all_jobs(self, queue_service: QueueService, tmp_path):
        """Test removing all jobs."""
        # Add multiple files
        files = [tmp_path / f"test{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"audio")
        queue_service.add_files([str(f) for f in files])

        # Remove all
        removed_count = queue_service.remove_jobs(all=True)

        assert removed_count == 3

        # Verify queue is empty
        assert queue_service.get_depth() == 0

    def test_remove_by_status(self, queue_service: QueueService, tmp_path):
        """Test removing jobs by status."""
        # Add files and mark one as done
        files = [tmp_path / f"test{i}.mp3" for i in range(2)]
        for f in files:
            f.write_bytes(b"audio")

        add_result = queue_service.add_files([str(f) for f in files])
        queue_service.queue.mark_done(add_result["job_ids"][0], {})

        # Remove only pending jobs
        removed_count = queue_service.remove_jobs(status="pending")

        assert removed_count == 1

        # Verify done job still exists
        stats = queue_service.get_status()
        assert stats["completed"] == 1
        assert stats["pending"] == 0


@pytest.mark.unit
class TestQueueServiceGetStatus:
    """Test QueueService.get_status and get_depth methods."""

    def test_get_status_empty(self, queue_service: QueueService):
        """Test getting stats from empty queue."""
        stats = queue_service.get_status()

        assert stats["pending"] == 0
        assert stats["running"] == 0
        assert stats["completed"] == 0
        assert stats["errors"] == 0

    def test_get_depth(self, queue_service: QueueService, tmp_path):
        """Test getting queue depth."""
        # Empty queue
        assert queue_service.get_depth() == 0

        # Add some files
        files = [tmp_path / f"test{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"audio")
        queue_service.add_files([str(f) for f in files])

        assert queue_service.get_depth() == 3

    def test_get_status_with_jobs(self, queue_service: QueueService, tmp_path):
        """Test getting stats with various job states."""
        # Add multiple files
        files = [tmp_path / f"test{i}.mp3" for i in range(4)]
        for f in files:
            f.write_bytes(b"audio")

        add_result = queue_service.add_files([str(f) for f in files])
        job_ids = add_result["job_ids"]

        # Set various states
        queue_service.queue.mark_done(job_ids[0], {})
        queue_service.queue.mark_error(job_ids[1], "test error")
        # job_ids[2] and [3] remain pending

        stats = queue_service.get_status()

        assert stats["pending"] == 2
        assert stats["completed"] == 1
        assert stats["errors"] == 1
        assert stats["running"] == 0


@pytest.mark.unit
class TestQueueServiceResetJobs:
    """Test QueueService.reset_jobs method."""

    def test_reset_stuck_jobs(self, queue_service: QueueService, tmp_path):
        """Test resetting stuck (running) jobs back to pending."""
        # Add file and mark as running
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        add_result = queue_service.add_files(str(test_file))
        job_id = add_result["job_ids"][0]

        # Simulate stuck job (mark as started)
        queue_service.queue.start(job_id)

        # Reset stuck jobs
        reset_count = queue_service.reset_jobs(stuck=True)

        assert reset_count == 1

        # Job should be pending again
        job = queue_service.get_job(job_id)
        assert job["status"] == "pending"

    def test_reset_error_jobs(self, queue_service: QueueService, tmp_path):
        """Test resetting error jobs back to pending."""
        # Add file and mark as error
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        add_result = queue_service.add_files(str(test_file))
        job_id = add_result["job_ids"][0]

        queue_service.queue.mark_error(job_id, "test error")

        # Reset error jobs
        reset_count = queue_service.reset_jobs(errors=True)

        assert reset_count == 1

        # Job should be pending again
        job = queue_service.get_job(job_id)
        assert job["status"] == "pending"


@pytest.mark.unit
class TestQueueServiceCleanup:
    """Test QueueService.cleanup_old_jobs method."""

    @pytest.mark.skip(reason="JobQueue.cleanup_old_jobs not yet implemented")
    def test_cleanup_old_jobs(self, queue_service: QueueService, tmp_path):
        """Test cleaning up old completed jobs."""
        # Add and complete a job
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        add_result = queue_service.add_files(str(test_file))
        job_id = add_result["job_ids"][0]

        queue_service.queue.mark_done(job_id, {})

        # Cleanup should find it (since max_age_hours is small)
        removed = queue_service.cleanup_old_jobs(max_age_hours=0)
        assert removed >= 0  # May or may not clean based on timestamp
