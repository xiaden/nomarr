"""
Unit tests for nomarr.data.queue module (ProcessingQueue and Job classes).
"""

import os
import tempfile

import pytest

from nomarr.persistence.db import Database
from nomarr.services.queue_svc import Job, ProcessingQueue


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        yield db
        db.close()


@pytest.fixture
def queue(temp_db):
    """Create a ProcessingQueue instance with a temporary database."""
    return ProcessingQueue(temp_db)


class TestJobClass:
    """Test the Job dataclass."""

    def test_job_creation_from_row(self):
        """Test Job can be created from database row dict."""
        row = {
            "id": 1,
            "path": "/music/test.mp3",
            "status": "pending",
            "added_at": "2025-11-07 12:00:00",
            "started_at": None,
            "done_at": None,
            "error_message": None,
            "results": None,
        }
        job = Job(**row)
        assert job.id == 1
        assert job.path == "/music/test.mp3"
        assert job.status == "pending"

    def test_job_to_dict(self):
        """Test Job.to_dict() returns correct dictionary."""
        row = {
            "id": 2,
            "path": "/music/another.mp3",
            "status": "done",
            "created_at": "2025-11-07 12:00:00",
            "started_at": "2025-11-07 12:01:00",
            "finished_at": "2025-11-07 12:02:00",
            "error_message": None,
            "force": True,
        }
        job = Job(**row)
        job_dict = job.to_dict()

        assert job_dict.id == 2
        assert job_dict.path == "/music/another.mp3"
        assert job_dict.status == "done"
        assert job_dict.created_at is not None
        assert job_dict.finished_at is not None


class TestProcessingQueueAdd:
    """Test ProcessingQueue.add() method."""

    def test_add_new_job(self, queue):
        """Test adding a new job to the queue."""
        job_id = queue.add("/music/test.mp3")
        assert job_id > 0

        job = queue.get(job_id)
        assert job is not None
        assert job.path == "/music/test.mp3"
        assert job.status == "pending"

    def test_add_duplicate_without_force(self, queue):
        """Test adding duplicate job without force always creates new job."""
        # ProcessingQueue.add() always creates a new job - no deduplication at this layer
        job_id1 = queue.add("/music/test.mp3")
        job_id2 = queue.add("/music/test.mp3")
        assert job_id2 > job_id1  # New job created

    def test_add_duplicate_with_force(self, queue):
        """Test adding duplicate job with force=True creates new job."""
        job_id1 = queue.add("/music/test.mp3", force=False)
        queue.mark_done(job_id1)  # Mark first as done

        job_id2 = queue.add("/music/test.mp3", force=True)
        assert job_id2 != job_id1

        job2 = queue.get(job_id2)
        assert job2.status == "pending"


class TestProcessingQueueGet:
    """Test ProcessingQueue.get() method."""

    def test_get_existing_job(self, queue):
        """Test getting an existing job by ID."""
        job_id = queue.add("/music/test.mp3")
        job = queue.get(job_id)

        assert job is not None
        assert job.id == job_id
        assert job.path == "/music/test.mp3"

    def test_get_nonexistent_job(self, queue):
        """Test getting a nonexistent job returns None."""
        job = queue.get(99999)
        assert job is None


class TestProcessingQueueList:
    """Test ProcessingQueue.list_jobs() method."""

    def test_list_empty_queue(self, queue):
        """Test listing jobs from empty queue."""
        jobs, total = queue.list_jobs()
        assert jobs == []
        assert total == 0

    def test_list_all_jobs(self, queue):
        """Test listing all jobs without filters."""
        queue.add("/music/test1.mp3")
        queue.add("/music/test2.mp3")
        queue.add("/music/test3.mp3")

        jobs, total = queue.list_jobs(limit=10)
        assert len(jobs) == 3
        assert total == 3

    def test_list_with_limit(self, queue):
        """Test listing jobs with limit."""
        for i in range(5):
            queue.add(f"/music/test{i}.mp3")

        jobs, total = queue.list_jobs(limit=2)
        assert len(jobs) == 2
        assert total == 5

    def test_list_with_offset(self, queue):
        """Test listing jobs with offset."""
        ids = []
        for i in range(5):
            ids.append(queue.add(f"/music/test{i}.mp3"))

        jobs, total = queue.list_jobs(limit=10, offset=2)
        assert len(jobs) == 3
        assert total == 5

    def test_list_filter_by_status(self, queue):
        """Test listing jobs filtered by status."""
        id1 = queue.add("/music/test1.mp3")
        id2 = queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.mark_done(id1)
        queue.mark_error(id2, "Test error")

        # List pending only
        pending_jobs, pending_total = queue.list_jobs(status="pending")
        assert len(pending_jobs) == 1
        assert pending_total == 1
        assert pending_jobs[0].id == id3

        # List done only
        done_jobs, done_total = queue.list_jobs(status="done")
        assert len(done_jobs) == 1
        assert done_total == 1
        assert done_jobs[0].id == id1


class TestProcessingQueueStatusTransitions:
    """Test job status transition methods."""

    def test_start_job(self, queue):
        """Test starting a job."""
        job_id = queue.add("/music/test.mp3")
        queue.start(job_id)

        job = queue.get(job_id)
        assert job.status == "running"
        assert job.started_at is not None

    def test_mark_done(self, queue):
        """Test marking a job as done."""
        job_id = queue.add("/music/test.mp3")
        queue.start(job_id)

        results = {"tags_written": 10, "duration": 2.5}
        queue.mark_done(job_id, results)

        job = queue.get(job_id)
        assert job.status == "done"
        assert job.finished_at is not None  # Job uses finished_at, not done_at

    def test_mark_done_without_results(self, queue):
        """Test marking a job as done without results."""
        job_id = queue.add("/music/test.mp3")
        queue.start(job_id)
        queue.mark_done(job_id)

        job = queue.get(job_id)
        assert job.status == "done"

    def test_mark_error(self, queue):
        """Test marking a job as error."""
        job_id = queue.add("/music/test.mp3")
        queue.start(job_id)
        queue.mark_error(job_id, "Test error message")

        job = queue.get(job_id)
        assert job.status == "error"
        assert job.error_message == "Test error message"
        assert job.finished_at is not None  # Job uses finished_at, not done_at

    def test_update_status_generic(self, queue):
        """Test generic status update."""
        job_id = queue.add("/music/test.mp3")
        # Use "error" status since update_job only saves error_message for "done" or "error"
        queue.update_status(job_id, "error", error_message="Already tagged")

        job = queue.get(job_id)
        assert job.status == "error"
        assert job.error_message == "Already tagged"


class TestProcessingQueueDelete:
    """Test job deletion methods."""

    def test_delete_single_job(self, queue):
        """Test deleting a single job."""
        job_id = queue.add("/music/test.mp3")
        deleted_count = queue.delete(job_id)

        assert deleted_count == 1
        assert queue.get(job_id) is None

    def test_delete_nonexistent_job(self, queue):
        """Test deleting a nonexistent job."""
        deleted_count = queue.delete(99999)
        assert deleted_count == 0

    def test_delete_by_status(self, queue):
        """Test deleting jobs by status."""
        id1 = queue.add("/music/test1.mp3")
        id2 = queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.mark_done(id1)
        queue.mark_error(id2, "Error")

        # Delete all done jobs
        deleted_count = queue.delete_by_status(["done"])
        assert deleted_count == 1
        assert queue.get(id1) is None
        assert queue.get(id2) is not None
        assert queue.get(id3) is not None

    def test_delete_by_multiple_statuses(self, queue):
        """Test deleting jobs by multiple statuses."""
        id1 = queue.add("/music/test1.mp3")
        id2 = queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.mark_done(id1)
        queue.mark_error(id2, "Error")

        # Delete both done and error
        deleted_count = queue.delete_by_status(["done", "error"])
        assert deleted_count == 2
        assert queue.get(id1) is None
        assert queue.get(id2) is None
        assert queue.get(id3) is not None


class TestProcessingQueueDepth:
    """Test queue depth calculation."""

    def test_depth_empty_queue(self, queue):
        """Test depth of empty queue."""
        assert queue.depth() == 0

    def test_depth_with_pending_jobs(self, queue):
        """Test depth counts only pending jobs."""
        queue.add("/music/test1.mp3")
        queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.mark_done(id3)

        assert queue.depth() == 2


class TestProcessingQueueReset:
    """Test job reset methods."""

    def test_reset_error_jobs(self, queue):
        """Test resetting error jobs to pending."""
        id1 = queue.add("/music/test1.mp3")
        id2 = queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.mark_error(id1, "Error 1")
        queue.mark_error(id2, "Error 2")
        queue.mark_done(id3)

        reset_count = queue.reset_error_jobs()
        assert reset_count == 2

        job1 = queue.get(id1)
        assert job1.status == "pending"
        assert job1.error_message is None

    def test_reset_stuck_jobs(self, queue):
        """Test resetting stuck (running) jobs to pending."""
        id1 = queue.add("/music/test1.mp3")
        id2 = queue.add("/music/test2.mp3")
        id3 = queue.add("/music/test3.mp3")

        queue.start(id1)
        queue.start(id2)
        queue.mark_done(id3)

        reset_count = queue.reset_stuck_jobs()
        assert reset_count == 2

        job1 = queue.get(id1)
        assert job1.status == "pending"
        assert job1.started_at is None
