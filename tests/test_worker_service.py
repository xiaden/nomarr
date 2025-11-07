"""
Tests for WorkerService (services/worker.py).
"""

import pytest

from nomarr.data.db import Database
from nomarr.data.queue import JobQueue
from nomarr.services.worker import WorkerService


@pytest.fixture
def worker_service(temp_db: str) -> WorkerService:
    """Create a WorkerService instance with fresh database."""
    db = Database(temp_db)
    queue = JobQueue(db)
    return WorkerService(db, queue, default_enabled=False, worker_count=1)


@pytest.mark.unit
class TestWorkerServiceEnabled:
    """Test WorkerService enable/disable functionality."""

    def test_is_enabled_default(self, worker_service: WorkerService):
        """Test default enabled state from constructor."""
        # We created with default_enabled=False
        assert worker_service.is_enabled() is False

    def test_enable(self, worker_service: WorkerService):
        """Test enabling worker."""
        worker_service.enable()
        assert worker_service.is_enabled() is True

    def test_disable(self, worker_service: WorkerService):
        """Test disabling worker."""
        worker_service.enable()
        assert worker_service.is_enabled() is True

        worker_service.disable()
        assert worker_service.is_enabled() is False

    def test_enable_persists_to_db(self, worker_service: WorkerService):
        """Test that enabled state persists to database."""
        worker_service.enable()

        # Check DB directly
        cursor = worker_service.db.conn.execute("SELECT value FROM meta WHERE key='worker_enabled'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "true"

    def test_disable_persists_to_db(self, worker_service: WorkerService):
        """Test that disabled state persists to database."""
        worker_service.disable()

        # Check DB directly
        cursor = worker_service.db.conn.execute("SELECT value FROM meta WHERE key='worker_enabled'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "false"


@pytest.mark.unit
class TestWorkerServiceStatus:
    """Test WorkerService.get_status method."""

    def test_get_status_disabled(self, worker_service: WorkerService):
        """Test getting status when worker is disabled."""
        status = worker_service.get_status()

        assert status["enabled"] is False
        assert status["running"] == 0
        assert status["worker_count"] == 1
        assert status["workers"] == []

    def test_get_status_enabled_not_started(self, worker_service: WorkerService):
        """Test getting status when enabled but not started."""
        worker_service.enable()
        status = worker_service.get_status()

        assert status["enabled"] is True
        assert status["running"] == 0
        assert status["worker_count"] == 1
        assert status["workers"] == []


@pytest.mark.unit
class TestWorkerServicePauseResume:
    """Test WorkerService pause/resume functionality."""

    def test_pause_when_disabled(self, worker_service: WorkerService):
        """Test pausing when already disabled."""
        result = worker_service.pause()

        # pause() returns get_status() dict
        assert result["enabled"] is False
        assert result["running"] == 0

    def test_pause_when_enabled(self, worker_service: WorkerService):
        """Test pausing when enabled."""
        worker_service.enable()
        result = worker_service.pause()

        # pause() disables and returns status
        assert result["enabled"] is False
        assert worker_service.is_enabled() is False

    def test_resume_when_disabled(self, worker_service: WorkerService):
        """Test resuming from disabled state."""
        # Note: resume() tries to start workers, which requires TaggerWorker
        # For now, just test that enable() works - full worker lifecycle
        # requires ProcessingCoordinator mock
        worker_service.enable()
        assert worker_service.is_enabled() is True

    def test_resume_when_already_enabled(self, worker_service: WorkerService):
        """Test resuming when already enabled."""
        worker_service.enable()
        assert worker_service.is_enabled() is True
        # Already enabled, nothing more to test without mocking workers


@pytest.mark.unit
class TestWorkerServiceCleanup:
    """Test WorkerService.cleanup_orphaned_jobs method."""

    def test_cleanup_orphaned_jobs_none(self, worker_service: WorkerService, tmp_path):
        """Test cleanup when no orphaned jobs exist."""
        # Add a pending job
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        worker_service.queue.add(str(test_file))

        cleaned = worker_service.cleanup_orphaned_jobs()
        assert cleaned == 0

    def test_cleanup_orphaned_jobs_running(self, worker_service: WorkerService, tmp_path):
        """Test cleanup resets stuck 'running' jobs."""
        # Add a job and mark it as running
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        job_id = worker_service.queue.add(str(test_file))
        worker_service.queue.start(job_id)

        # Verify it's running
        job = worker_service.queue.get(job_id)
        assert job.status == "running"

        # Cleanup
        cleaned = worker_service.cleanup_orphaned_jobs()
        assert cleaned == 1

        # Verify it's now pending
        job = worker_service.queue.get(job_id)
        assert job.status == "pending"


@pytest.mark.unit
class TestWorkerServiceWaitIdle:
    """Test WorkerService.wait_until_idle method."""

    def test_wait_until_idle_already_idle(self, worker_service: WorkerService):
        """Test waiting when queue is already empty."""
        result = worker_service.wait_until_idle(timeout=1, poll_interval=0.1)
        assert result is True

    def test_wait_until_idle_with_done_jobs(self, worker_service: WorkerService, tmp_path):
        """Test waiting when only completed jobs exist."""
        # Add a job and mark it done
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        job_id = worker_service.queue.add(str(test_file))
        worker_service.queue.mark_done(job_id, {})

        result = worker_service.wait_until_idle(timeout=1, poll_interval=0.1)
        assert result is True

    def test_wait_until_idle_with_pending_times_out(self, worker_service: WorkerService, tmp_path):
        """Test waiting when pending jobs exist (does not block - only checks running)."""
        # Add a pending job
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        worker_service.queue.add(str(test_file))

        # wait_until_idle only checks for RUNNING jobs, not pending
        # So this should return True immediately (no running jobs)
        result = worker_service.wait_until_idle(timeout=0.2, poll_interval=0.1)
        assert result is True

    def test_wait_until_idle_with_running_times_out(self, worker_service: WorkerService, tmp_path):
        """Test waiting times out when running jobs remain."""
        # Add a job and mark it as running
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")
        job_id = worker_service.queue.add(str(test_file))
        worker_service.queue.start(job_id)

        # Should timeout since job stays in running state
        result = worker_service.wait_until_idle(timeout=0.2, poll_interval=0.1)
        assert result is False
