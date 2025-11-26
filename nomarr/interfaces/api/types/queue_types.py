"""
Queue API response types.

External API contracts for queue and worker endpoints.
These are Pydantic models that transform internal DTOs into API responses.

Architecture:
- These types are owned by the interface layer
- They define what external clients see (REST API shapes)
- They transform internal DTOs via .from_dto() classmethods
- Services and lower layers should NOT import from this module
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel
from typing_extensions import Self

from nomarr.helpers.dto.queue_dto import JobDict, ListJobsResult
from nomarr.services.queue_svc import QueueStatus
from nomarr.services.worker_svc import WorkerStatusResult

# ──────────────────────────────────────────────────────────────────────
# Queue Job Types
# ──────────────────────────────────────────────────────────────────────


QueueType = Literal["scan", "processing", "recalibration"]
JobStatus = Literal["pending", "processing", "done", "error"]


class QueueJobItem(BaseModel):
    """
    Unified queue job representation for API responses.

    Extends internal JobDict with API-specific fields.
    """

    id: int
    path: str
    status: str
    created_at: str | int | float
    started_at: str | int | float | None = None
    finished_at: str | int | float | None = None
    error_message: str | None = None
    force: bool = False
    queue_type: str = "processing"  # API-specific: which queue
    attempts: int = 0  # API-specific: retry count

    @classmethod
    def from_dto(cls, job: JobDict, queue_type: str = "processing", attempts: int = 0) -> Self:
        """
        Transform internal JobDict DTO to external API response.

        Args:
            job: Internal job DTO from service layer
            queue_type: Which queue this job belongs to (API-specific)
            attempts: Number of processing attempts (API-specific)

        Returns:
            API response model
        """
        return cls(
            **asdict(job),
            queue_type=queue_type,
            attempts=attempts,
        )


class QueueStatusResponse(BaseModel):
    """
    Response for queue status/depth endpoint.

    Provides counts of jobs in different states.
    """

    pending: int
    processing: int
    done: int
    error: int
    total: int

    @classmethod
    def from_dto(cls, status: QueueStatus) -> Self:
        """
        Transform internal QueueStatus DTO to external API response.

        Args:
            status: Internal queue status from service layer

        Returns:
            API response model with normalized field names
        """
        counts = status.counts
        # Map internal status names to API names
        return cls(
            pending=counts.get("pending", 0),
            processing=counts.get("running", 0) + counts.get("processing", 0),
            done=counts.get("done", 0),
            error=counts.get("error", 0),
            total=sum(counts.values()),
        )


class QueueJobsResponse(BaseModel):
    """Response wrapping a list of queue jobs."""

    jobs: list[QueueJobItem]
    total: int = 0
    limit: int = 50
    offset: int = 0

    @classmethod
    def from_dto(cls, result: ListJobsResult, queue_type: str = "processing") -> Self:
        """
        Transform internal ListJobsResult DTO to external API response.

        Args:
            result: Internal list result from service layer
            queue_type: Which queue these jobs belong to

        Returns:
            API response model with transformed job items
        """
        return cls(
            jobs=[QueueJobItem.from_dto(job, queue_type=queue_type) for job in result.jobs],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
        )


# ──────────────────────────────────────────────────────────────────────
# Worker Status Types
# ──────────────────────────────────────────────────────────────────────


class WorkerStatusItem(BaseModel):
    """
    Status information for a single worker.

    API representation of worker state.
    """

    name: str
    worker_id: int | None = None
    alive: bool = True
    is_busy: bool = False
    last_heartbeat: float | int | None = None
    queue_type: str = "processing"


class WorkersStatusResponse(BaseModel):
    """Response for worker status listing."""

    enabled: bool
    worker_count: int
    running: int
    workers: list[WorkerStatusItem]

    @classmethod
    def from_dto(cls, status: WorkerStatusResult, queue_type: str = "processing") -> Self:
        """
        Transform internal WorkerStatusResult DTO to external API response.

        Args:
            status: Internal worker status from service layer
            queue_type: Which queue these workers process

        Returns:
            API response model
        """
        # Transform worker dicts to WorkerStatusItem models
        worker_items = [
            WorkerStatusItem(
                name=w.get("name", "unknown"),
                worker_id=w.get("id"),
                alive=w.get("alive", True),
                is_busy=False,  # Not tracked in current worker dict
                queue_type=queue_type,
            )
            for w in status.workers
        ]

        return cls(
            enabled=status.enabled,
            worker_count=status.worker_count,
            running=status.running,
            workers=worker_items,
        )


# ──────────────────────────────────────────────────────────────────────
# Operation Result Types
# ──────────────────────────────────────────────────────────────────────


class OperationResult(BaseModel):
    """Generic success/failure result."""

    status: str
    message: str


class JobRemovalResult(BaseModel):
    """Result of removing jobs from queue."""

    removed: int
    message: str
