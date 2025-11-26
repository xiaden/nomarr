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
class JobDict:
    """Result from queue_service.to_dict - represents a job as dict for API."""

    id: int
    path: str
    status: str
    created_at: str
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

    jobs: list[JobDict]
    total: int
    limit: int
    offset: int
