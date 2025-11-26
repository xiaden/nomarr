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
    started_at: str | None
    finished_at: str | None
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
    """Result from enqueue_files_workflow and queue_service.add_files."""

    job_ids: list[int]
    files_queued: int
    queue_depth: int
    paths: list[str]
