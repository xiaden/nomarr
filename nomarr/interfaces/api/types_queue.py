"""
Shared type definitions for queue and worker API responses.

This module defines the unified response shapes for all three queues
(scan, processing, recalibration) and their associated workers.

These types are owned by the interface layer and represent HTTP/JSON shapes.
Services and lower layers should NOT import from this module.
"""

from typing import Literal

from typing_extensions import TypedDict

# ──────────────────────────────────────────────────────────────────────
# Queue Job Types
# ──────────────────────────────────────────────────────────────────────


QueueType = Literal["scan", "processing", "recalibration"]
JobStatus = Literal["pending", "processing", "done", "error"]


class QueueJobItem(TypedDict, total=False):
    """
    Unified queue job representation across all three queues.

    Fields:
        id: Job ID
        path: File path
        status: Job status (pending, processing, done, error)
        created_at: Timestamp when job was created
        started_at: Timestamp when job started processing (optional)
        finished_at: Timestamp when job finished (optional)
        error_message: Error message if job failed (optional)
        force: Whether to force reprocessing (optional)
        queue_type: Which queue this job belongs to (optional)
        attempts: Number of processing attempts (optional)
    """

    id: int
    path: str
    status: str
    created_at: float | int | str
    started_at: float | int | str | None
    finished_at: float | int | str | None
    error_message: str | None
    force: bool
    queue_type: str
    attempts: int


class QueueStatusResponse(TypedDict):
    """
    Response for queue status/depth endpoint.

    Provides counts of jobs in different states.
    """

    pending: int
    processing: int
    done: int
    error: int
    total: int


class QueueJobsResponse(TypedDict):
    """Response wrapping a list of queue jobs."""

    jobs: list[QueueJobItem]


# ──────────────────────────────────────────────────────────────────────
# Worker Status Types
# ──────────────────────────────────────────────────────────────────────


class WorkerStatusItem(TypedDict, total=False):
    """
    Status information for a single worker.

    Fields:
        name: Worker name/identifier
        worker_id: Internal worker ID (optional)
        alive: Whether worker is alive/responsive
        is_busy: Whether worker is currently processing
        last_heartbeat: Timestamp of last heartbeat (optional)
        queue_type: Which queue this worker processes (optional)
    """

    name: str
    worker_id: int
    alive: bool
    is_busy: bool
    last_heartbeat: float | int | None
    queue_type: str


class WorkersStatusResponse(TypedDict):
    """Response for worker status listing."""

    workers: list[WorkerStatusItem]
    status: str  # Overall status message


# ──────────────────────────────────────────────────────────────────────
# Operation Result Types
# ──────────────────────────────────────────────────────────────────────


class OperationResult(TypedDict):
    """Generic success/failure result."""

    status: str
    message: str


class JobRemovalResult(TypedDict):
    """Result of removing jobs from queue."""

    removed: int
    message: str
