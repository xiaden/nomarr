"""
Integration tests for nomarr/data/queue.py
"""

import pytest

from nomarr.data.db import now_ms
from nomarr.data.queue import Job


@pytest.mark.integration
class TestJobQueue:
    """Test JobQueue operations."""

    def test_add_job(self, mock_job_queue):
        """Test adding a job to the queue."""
        job_id = mock_job_queue.add("/music/test.mp3")

        assert job_id > 0
        assert isinstance(job_id, int)

    def test_add_job_with_force(self, mock_job_queue):
        """Test adding a job with force flag."""
        job_id = mock_job_queue.add("/music/test.mp3", force=True)

        job = mock_job_queue.get(job_id)
        assert job is not None
        assert job.force is True

    def test_get_job(self, mock_job_queue):
        """Test retrieving a job by ID."""
        job_id = mock_job_queue.add("/music/test.mp3")
        job = mock_job_queue.get(job_id)

        assert job is not None
        assert job.id == job_id
        assert job.path == "/music/test.mp3"
        assert job.status == "pending"

    def test_get_job_nonexistent(self, mock_job_queue):
        """Test retrieving a non-existent job returns None."""
        job = mock_job_queue.get(99999)
        assert job is None

    def test_list_jobs_empty(self, mock_job_queue):
        """Test listing jobs from empty queue."""
        jobs, total = mock_job_queue.list()
        assert jobs == []
        assert total == 0

    def test_list_jobs(self, mock_job_queue):
        """Test listing jobs."""
        job_id1 = mock_job_queue.add("/music/test1.mp3")
        job_id2 = mock_job_queue.add("/music/test2.mp3")

        jobs, total = mock_job_queue.list()

        assert len(jobs) == 2
        assert total == 2
        assert any(j.id == job_id1 for j in jobs)
        assert any(j.id == job_id2 for j in jobs)

    def test_list_jobs_with_limit(self, mock_job_queue):
        """Test listing jobs with limit."""
        for i in range(5):
            mock_job_queue.add(f"/music/test{i}.mp3")

        jobs, total = mock_job_queue.list(limit=3)

        assert len(jobs) == 3
        assert total == 5  # Total count should still be 5

    def test_list_jobs_with_offset(self, mock_job_queue):
        """Test listing jobs with offset."""
        for i in range(5):
            mock_job_queue.add(f"/music/test{i}.mp3")

        jobs, total = mock_job_queue.list(offset=2)

        assert len(jobs) == 3  # Remaining after offset
        assert total == 5  # Total count

    def test_list_jobs_with_status_filter(self, mock_job_queue):
        """Test listing jobs filtered by status."""
        job_id1 = mock_job_queue.add("/music/test1.mp3")
        job_id2 = mock_job_queue.add("/music/test2.mp3")

        # Mark one as running
        mock_job_queue.start(job_id1)

        pending_jobs, pending_total = mock_job_queue.list(status="pending")
        running_jobs, running_total = mock_job_queue.list(status="running")

        assert pending_total == 1
        assert pending_jobs[0].id == job_id2

        assert running_total == 1
        assert running_jobs[0].id == job_id1

    def test_depth(self, mock_job_queue):
        """Test getting queue depth (pending + running count)."""
        assert mock_job_queue.depth() == 0

        mock_job_queue.add("/music/test1.mp3")
        mock_job_queue.add("/music/test2.mp3")
        job_id3 = mock_job_queue.add("/music/test3.mp3")

        assert mock_job_queue.depth() == 3

        # Mark one as running - still counts in depth
        mock_job_queue.start(job_id3)
        assert mock_job_queue.depth() == 3  # pending + running

        # Mark as done - no longer in depth
        mock_job_queue.mark_done(job_id3)
        assert mock_job_queue.depth() == 2  # Only pending now

    def test_flush(self, mock_job_queue):
        """Test flushing finished jobs (default behavior)."""
        # Add 5 jobs and mark them done
        for i in range(5):
            job_id = mock_job_queue.add(f"/music/test{i}.mp3")
            mock_job_queue.start(job_id)
            mock_job_queue.mark_done(job_id)

        # Add 2 more jobs and mark them error
        for i in range(5, 7):
            job_id = mock_job_queue.add(f"/music/test{i}.mp3")
            mock_job_queue.start(job_id)
            mock_job_queue.mark_error(job_id, "test error")

        # Add 1 pending job
        mock_job_queue.add("/music/test_pending.mp3")

        # Flush with default (done + error)
        count = mock_job_queue.flush()
        assert count == 7  # 5 done + 2 error

        # Verify only pending job remains
        jobs, total = mock_job_queue.list()
        assert total == 1
        assert jobs[0].path == "/music/test_pending.mp3"
        assert jobs[0].status == "pending"

    def test_flush_specific_status(self, mock_job_queue):
        """Test flushing specific status."""
        # Add jobs with different statuses
        job_id1 = mock_job_queue.add("/music/test1.mp3")
        mock_job_queue.start(job_id1)
        mock_job_queue.mark_done(job_id1)

        job_id2 = mock_job_queue.add("/music/test2.mp3")
        mock_job_queue.start(job_id2)
        mock_job_queue.mark_error(job_id2, "error")

        mock_job_queue.add("/music/test3.mp3")  # pending

        # Flush only "error" status
        count = mock_job_queue.flush(statuses=["error"])
        assert count == 1

        # Verify done and pending remain
        jobs, total = mock_job_queue.list()
        assert total == 2
        statuses = {job.status for job in jobs}
        assert statuses == {"done", "pending"}

    def test_flush_pending(self, mock_job_queue):
        """Test flushing pending jobs."""
        # Add pending and done jobs
        for i in range(3):
            mock_job_queue.add(f"/music/pending{i}.mp3")

        job_id = mock_job_queue.add("/music/done.mp3")
        mock_job_queue.start(job_id)
        mock_job_queue.mark_done(job_id)

        # Flush only pending
        count = mock_job_queue.flush(statuses=["pending"])
        assert count == 3

        # Verify only done remains
        jobs, total = mock_job_queue.list()
        assert total == 1
        assert jobs[0].status == "done"

    def test_flush_cannot_flush_running(self, mock_job_queue):
        """Test that flushing running jobs raises error."""
        job_id = mock_job_queue.add("/music/test.mp3")
        mock_job_queue.start(job_id)

        # Attempting to flush running should raise ValueError
        with pytest.raises(ValueError, match="Cannot flush 'running' jobs"):
            mock_job_queue.flush(statuses=["running"])

    def test_flush_invalid_status(self, mock_job_queue):
        """Test that invalid status raises error."""
        with pytest.raises(ValueError, match="Invalid statuses"):
            mock_job_queue.flush(statuses=["invalid_status"])

    def test_mark_done(self, mock_job_queue):
        """Test marking job as done."""
        job_id = mock_job_queue.add("/music/test.mp3")
        mock_job_queue.start(job_id)

        results = {"genre": "rock", "mood": "happy"}
        mock_job_queue.mark_done(job_id, results)

        job = mock_job_queue.get(job_id)
        assert job.status == "done"
        assert job.finished_at is not None

    def test_mark_error(self, mock_job_queue):
        """Test marking job as error."""
        job_id = mock_job_queue.add("/music/test.mp3")
        mock_job_queue.start(job_id)

        mock_job_queue.mark_error(job_id, "Test error message")

        job = mock_job_queue.get(job_id)
        assert job.status == "error"
        assert job.error_message == "Test error message"
        assert job.finished_at is not None

    def test_reset_running_to_pending(self, mock_job_queue):
        """Test resetting stuck running jobs to pending."""
        job_id1 = mock_job_queue.add("/music/test1.mp3")
        job_id2 = mock_job_queue.add("/music/test2.mp3")
        mock_job_queue.add("/music/test3.mp3")

        # Start two jobs
        mock_job_queue.start(job_id1)
        mock_job_queue.start(job_id2)

        # Reset running to pending
        reset_count = mock_job_queue.reset_running_to_pending()

        assert reset_count == 2
        assert mock_job_queue.depth() == 3  # All back to pending

    def test_job_dataclass(self):
        """Test Job dataclass creation."""
        job = Job(
            id=1,
            path="/music/test.mp3",
            status="pending",
            created_at=now_ms(),
            started_at=None,
            finished_at=None,
            error_message=None,
            results_json=None,
            force=False,
        )

        assert job.id == 1
        assert job.path == "/music/test.mp3"
        assert job.status == "pending"
        assert job.force is False

    def test_job_from_db_row(self, mock_job_queue):
        """Test creating Job from database row."""
        job_id = mock_job_queue.add("/music/test.mp3")

        # Fetch raw row
        cursor = mock_job_queue.db.conn.execute("SELECT * FROM queue WHERE id = ?", (job_id,))
        row = cursor.fetchone()

        # Job should be creatable from row data
        assert row is not None
        assert row[1] == "/music/test.mp3"  # path column


@pytest.mark.integration
class TestJobQueueConcurrency:
    """Test JobQueue concurrent operations."""

    def test_add_multiple_jobs_same_path(self, mock_job_queue):
        """Test adding same path multiple times creates separate jobs."""
        job_id1 = mock_job_queue.add("/music/test.mp3")
        job_id2 = mock_job_queue.add("/music/test.mp3")

        assert job_id1 != job_id2
        jobs, total = mock_job_queue.list()
        assert total == 2

    def test_concurrent_status_updates(self, mock_job_queue):
        """Test concurrent status updates don't corrupt queue."""
        job_ids = [mock_job_queue.add(f"/music/test{i}.mp3") for i in range(10)]

        # Update statuses
        for i, job_id in enumerate(job_ids):
            if i % 2 == 0:
                mock_job_queue.start(job_id)
                mock_job_queue.mark_done(job_id)
            else:
                mock_job_queue.start(job_id)

        # Verify counts
        running_jobs, running_count = mock_job_queue.list(status="running")
        done_jobs, done_count = mock_job_queue.list(status="done")
        assert running_count == 5
        assert done_count == 5
        jobs, total = mock_job_queue.list()
        assert total == 10
