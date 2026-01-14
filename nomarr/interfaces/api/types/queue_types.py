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

from pydantic import BaseModel
from typing_extensions import Self

from nomarr.helpers.dto import admin_dto
from nomarr.helpers.dto.queue_dto import (
    FlushResult,
    Job,
    ListJobsResult,
    QueueStatus,
)

# ──────────────────────────────────────────────────────────────────────
# Queue Request Types
# ──────────────────────────────────────────────────────────────────────


class RemoveJobRequest(BaseModel):
    """Request to remove a specific job from the queue."""

    job_id: str


class FlushRequest(BaseModel):
    """Request to flush jobs by status."""

    statuses: list[str] | None = None  # e.g., ["pending","error"]; None => default


# ──────────────────────────────────────────────────────────────────────
# Queue Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class QueueJobResponse(BaseModel):
    """
    Single queue job response.

    Maps directly to Job DTO from helpers/dto/queue_dto.py
    """

    id: str  # ArangoDB _id
    path: str
    status: str
    created_at: int
    started_at: int | None
    finished_at: int | None
    error_message: str | None
    force: bool

    @classmethod
    def from_dto(cls, job: Job) -> Self:
        """
        Transform internal Job DTO to external API response.

        Args:
            job: Internal job DTO from service layer

        Returns:
            API response model
        """
        return cls(
            id=job.id,
            path=job.path,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_message=job.error_message,
            force=job.force,
        )


class ListJobsResponse(BaseModel):
    """
    Response for list jobs endpoint.

    Maps to ListJobsResult DTO from helpers/dto/queue_dto.py
    """

    jobs: list[QueueJobResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, result: ListJobsResult) -> Self:
        """
        Transform internal ListJobsResult DTO to external API response.

        Args:
            result: Internal list result from service layer

        Returns:
            API response model with transformed job items
        """
        return cls(
            jobs=[QueueJobResponse.from_dto(job) for job in result.jobs],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
        )


class QueueStatusResponse(BaseModel):
    """
    Response for queue status/depth endpoint.

    Maps to QueueStatus DTO from helpers/dto/queue_dto.py.
    Flattens the structure and renames fields for frontend compatibility.
    """

    pending: int
    running: int
    completed: int
    errors: int

    @classmethod
    def from_dto(cls, status: QueueStatus) -> Self:
        """
        Transform internal QueueStatus DTO to external API response.

        Args:
            status: Internal queue status from service layer

        Returns:
            API response model with flattened structure
        """
        return cls(
            pending=status.counts.get("pending", 0),
            running=status.counts.get("running", 0),
            completed=status.counts.get("completed", 0),
            errors=status.counts.get("error", 0),
        )


class FlushResponse(BaseModel):
    """
    Response for flush operation.

    Maps to FlushResult DTO from helpers/dto/queue_dto.py
    """

    flushed_statuses: list[str]
    removed: int

    @classmethod
    def from_dto(cls, result: FlushResult) -> Self:
        """
        Transform internal FlushResult DTO to external API response.

        Args:
            result: Internal flush result from service layer

        Returns:
            API response model
        """
        return cls(
            flushed_statuses=result.flushed_statuses,
            removed=result.removed,
        )


# ──────────────────────────────────────────────────────────────────────
# Legacy Response Types (Kept for backward compatibility)
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Queue Job Types
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Worker Status Types
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Operation Result Types
# ──────────────────────────────────────────────────────────────────────


class OperationResult(BaseModel):
    """Generic success/failure result."""

    status: str
    message: str

    @classmethod
    def from_dto(cls, dto: admin_dto.WorkerOperationResult) -> OperationResult:
        """Convert worker operation DTO to Pydantic response model."""
        return cls(status=dto.status, message=dto.message)


class JobRemovalResult(BaseModel):
    """Result of removing jobs from queue."""

    removed: int
    message: str

    @classmethod
    def from_dto(cls, dto: admin_dto.JobRemovalResult) -> JobRemovalResult:
        """Convert admin DTO to Pydantic response model."""
        return cls(removed=dto.removed, message=dto.message)
