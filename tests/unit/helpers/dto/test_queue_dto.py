"""
Unit tests for nomarr.helpers.dto.queue_dto module.

Tests the queue-related DTOs.
"""

import pytest

from nomarr.helpers.dto.queue_dto import (
    BatchEnqueuePathResult,
    BatchEnqueueResult,
    DequeueResult,
    EnqueueFilesResult,
    FlushResult,
    Job,
    ListJobsResult,
    QueueStatus,
)


class TestJob:
    """Tests for Job dataclass."""

    @pytest.mark.unit
    def test_can_create_pending_job(self) -> None:
        """Job should be creatable for a pending job."""
        job = Job(
            id="queue/12345",
            path="/music/song.mp3",
            status="pending",
            created_at=1700000000000,
            started_at=None,
            finished_at=None,
            error_message=None,
            force=False,
        )
        assert job.id == "queue/12345"
        assert job.path == "/music/song.mp3"
        assert job.status == "pending"
        assert job.started_at is None
        assert job.finished_at is None
        assert job.error_message is None
        assert job.force is False

    @pytest.mark.unit
    def test_can_create_completed_job(self) -> None:
        """Job should be creatable for a completed job."""
        job = Job(
            id="queue/12345",
            path="/music/song.mp3",
            status="done",
            created_at=1700000000000,
            started_at=1700000001000,
            finished_at=1700000002000,
            error_message=None,
            force=True,
        )
        assert job.status == "done"
        assert job.started_at == 1700000001000
        assert job.finished_at == 1700000002000
        assert job.force is True

    @pytest.mark.unit
    def test_can_create_failed_job(self) -> None:
        """Job should be creatable for a failed job with error message."""
        job = Job(
            id="queue/12345",
            path="/music/song.mp3",
            status="error",
            created_at=1700000000000,
            started_at=1700000001000,
            finished_at=1700000002000,
            error_message="File not found",
            force=False,
        )
        assert job.status == "error"
        assert job.error_message == "File not found"


class TestDequeueResult:
    """Tests for DequeueResult dataclass."""

    @pytest.mark.unit
    def test_can_create_dequeue_result(self) -> None:
        """DequeueResult should store job_id, file_path, and force flag."""
        result = DequeueResult(
            job_id="queue/12345",
            file_path="/music/song.mp3",
            force=True,
        )
        assert result.job_id == "queue/12345"
        assert result.file_path == "/music/song.mp3"
        assert result.force is True


class TestListJobsResult:
    """Tests for ListJobsResult dataclass."""

    @pytest.mark.unit
    def test_can_create_with_empty_jobs(self) -> None:
        """ListJobsResult should work with empty job list."""
        result = ListJobsResult(
            jobs=[],
            total=0,
            limit=100,
            offset=0,
        )
        assert result.jobs == []
        assert result.total == 0

    @pytest.mark.unit
    def test_can_create_with_jobs(self) -> None:
        """ListJobsResult should store list of Job objects."""
        job = Job(
            id="queue/1",
            path="/music/song.mp3",
            status="pending",
            created_at=1700000000000,
            started_at=None,
            finished_at=None,
            error_message=None,
            force=False,
        )
        result = ListJobsResult(
            jobs=[job],
            total=1,
            limit=100,
            offset=0,
        )
        assert len(result.jobs) == 1
        assert result.jobs[0].id == "queue/1"


class TestFlushResult:
    """Tests for FlushResult dataclass."""

    @pytest.mark.unit
    def test_can_create_flush_result(self) -> None:
        """FlushResult should store flushed statuses and count."""
        result = FlushResult(
            flushed_statuses=["done", "error"],
            removed=42,
        )
        assert result.flushed_statuses == ["done", "error"]
        assert result.removed == 42


class TestQueueStatus:
    """Tests for QueueStatus dataclass."""

    @pytest.mark.unit
    def test_can_create_queue_status(self) -> None:
        """QueueStatus should store depth and counts by status."""
        result = QueueStatus(
            depth=100,
            counts={"pending": 80, "processing": 10, "done": 5, "error": 5},
        )
        assert result.depth == 100
        assert result.counts["pending"] == 80
        assert result.counts["processing"] == 10


class TestEnqueueFilesResult:
    """Tests for EnqueueFilesResult dataclass."""

    @pytest.mark.unit
    def test_can_create_enqueue_result(self) -> None:
        """EnqueueFilesResult should store enqueue operation results."""
        result = EnqueueFilesResult(
            job_ids=["queue/1", "queue/2"],
            files_queued=2,
            queue_depth=10,
            paths=["/music/song1.mp3", "/music/song2.mp3"],
        )
        assert len(result.job_ids) == 2
        assert result.files_queued == 2
        assert result.queue_depth == 10
        assert len(result.paths) == 2


class TestBatchEnqueuePathResult:
    """Tests for BatchEnqueuePathResult dataclass."""

    @pytest.mark.unit
    def test_can_create_success_result(self) -> None:
        """BatchEnqueuePathResult should store successful enqueue."""
        result = BatchEnqueuePathResult(
            path="/music/album",
            status="queued",
            message="10 files queued",
            files_queued=10,
            job_ids=["queue/1", "queue/2"],
        )
        assert result.status == "queued"
        assert result.files_queued == 10

    @pytest.mark.unit
    def test_can_create_error_result(self) -> None:
        """BatchEnqueuePathResult should store error result."""
        result = BatchEnqueuePathResult(
            path="/music/invalid",
            status="error",
            message="Path not found",
            files_queued=0,
            job_ids=None,
        )
        assert result.status == "error"
        assert result.job_ids is None


class TestBatchEnqueueResult:
    """Tests for BatchEnqueueResult dataclass."""

    @pytest.mark.unit
    def test_can_create_batch_result(self) -> None:
        """BatchEnqueueResult should aggregate multiple path results."""
        path_result = BatchEnqueuePathResult(
            path="/music/album",
            status="queued",
            message="5 files queued",
            files_queued=5,
        )
        result = BatchEnqueueResult(
            total_queued=5,
            total_errors=0,
            results=[path_result],
        )
        assert result.total_queued == 5
        assert result.total_errors == 0
        assert len(result.results) == 1
