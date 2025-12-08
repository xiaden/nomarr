"""
Queue domain DTOs.

Data transfer objects for queue service operations.
These form cross-layer contracts between services and interfaces.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Job:
    """
    Core queue job entity.

    Represents a queued processing job with lifecycle tracking.
    Used across queue service, library service, and worker operations.
    """

    id: int
    path: str
    status: str
    created_at: int
    started_at: int | None
    finished_at: int | None
    error_message: str | None
    force: bool


@dataclass
class DequeueResult:
    """Result from queue_service.dequeue."""

    job_id: int
    file_path: str
    force: bool


@dataclass
class ListJobsResult:
    """Result from queue_service.list_jobs."""

    jobs: list[Job]
    total: int
    limit: int
    offset: int


@dataclass
class FlushResult:
    """Result from queue_service.flush_by_statuses."""

    flushed_statuses: list[str]
    removed: int


@dataclass
class QueueStatus:
    """Result from queue_service.get_status."""

    depth: int
    counts: dict[str, int]


@dataclass
class EnqueueFilesResult:
    """Result from enqueue_files_workflow and queue_service.enqueue_files_for_tagging."""

    job_ids: list[int]
    files_queued: int
    queue_depth: int
    paths: list[str]


@dataclass
class BatchEnqueuePathResult:
    """Result for a single path in a batch enqueue operation."""

    path: str
    status: str  # "queued" or "error"
    message: str
    files_queued: int = 0
    job_ids: list[int] | None = None


@dataclass
class BatchEnqueueResult:
    """Result from queue_service.batch_add_files."""

    total_queued: int
    total_errors: int
    results: list[BatchEnqueuePathResult]
