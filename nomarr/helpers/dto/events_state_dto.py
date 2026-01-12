"""
Events state domain DTOs.

Data transfer objects for StateBroker's internal state representation.
These form internal contracts for SSE state payloads and future adapters.

These DTOs represent the internal structure of StateBroker's state management.
They are serialized to dicts for SSE wire format but provide type safety internally.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QueueState:
    """
    Queue statistics state.

    Represents current state of a processing queue (tag, library, calibration)
    or global aggregate state (queue_type=None).

    Used for SSE topics:
    - queue:status (global aggregate)
    - queue:{queue_type}:status (per-queue)
    - queue:*:status (all queues)
    """

    queue_type: str | None  # None for global aggregate, "tag"/"library"/"calibration" for per-queue
    pending: int
    running: int
    completed: int
    avg_time: float
    eta: float


@dataclass
class JobState:
    """
    Individual job state.

    Represents a single processing job with current status and results.

    Used for SSE topic:
    - queue:jobs
    """

    id: int
    path: str | None
    status: str
    error: str | None
    results: dict[str, Any] | None


@dataclass
class WorkerState:
    """
    Worker process state.

    Represents a worker process with current job and health status.
    Component format: "worker:{queue_type}:{id}"

    Used for SSE topics:
    - worker:{queue_type}:{id}:status (specific worker)
    - worker:{queue_type}:*:status (all workers for queue type)
    - worker:*:status (all workers)
    """

    component: str  # Full component ID: "worker:{queue_type}:{id}"
    id: int | None  # Parsed numeric worker ID if available
    queue_type: str | None  # Queue type: "tag", "library", "calibration"
    status: str  # Worker status: "starting", "healthy", "stopping", "failed", "crashed"
    pid: int | None  # Process ID
    current_job: int | None  # Currently processing job ID


@dataclass
class GPUHealthState:
    """
    GPU availability and health state.

    Tracks GPU dependency status for readiness probes and worker preflight checks.
    Populated by background GPU probe loop running nvidia-smi with timeout.

    Used for SSE topic:
    - system:gpu
    """

    status: str  # "available", "unavailable", or "unknown" (stale/missing)
    available: bool  # True if GPU is accessible and responding
    last_check_at: float | None  # Unix timestamp of last probe attempt
    last_ok_at: float | None  # Unix timestamp of last successful probe
    consecutive_failures: int  # Count of consecutive failed probes (resets on success)
    error_summary: str | None  # Short error message from last failed probe
    probe_id: str | None = None  # Unique probe identifier for tracking
    duration_ms: float | None = None  # Probe duration in milliseconds


@dataclass
class SystemHealthState:
    """
    System health state.

    Represents overall system health with error tracking.

    Used for SSE topic:
    - system:health
    """

    status: str  # "healthy", "degraded", "error", etc.
    errors: list[str]
    gpu: GPUHealthState | None = None  # GPU health facet (None if GPU not configured)
