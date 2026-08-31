"""App-state domain dataclasses.

This module defines ADR-041 domain objects produced by the ``AppDb``
persistence facade. ``ConfigOption`` represents a user configuration value,
``LockEntry`` the logical identity and lifecycle of a distributed lock, and the
resource/worker types (``CapacityEstimate``, ``ModelVramLimit``,
``GpuResourceSnapshot``) are persistence-independent domain values. These
objects deliberately do not expose the physical PostgreSQL key/value
representation.

Usage:
    from nomarr.helpers.dataclasses.app_dataclasses import (
        CapacityEstimate,
        ConfigOption,
        GpuResourceSnapshot,
        LockEntry,
        ModelVramLimit,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass(frozen=True, slots=True)
class ConfigOption:
    """A user configuration value identified by its configuration ``key``.

    This is the domain value the ``AppDb`` facade returns for configuration
    reads: ``value`` carries the configuration value (a scalar or JSON-compatible
    object) and ``key`` its logical configuration identity. It never exposes the
    underlying storage representation.
    """

    key: str
    value: Any


@dataclass(frozen=True, slots=True)
class CapacityEstimate:
    """Resource-consumption estimate for one model set.

    Produced by the ML capacity probe to drive admission control. ``gpu_capable``
    reflects whether the measured model set can run on the GPU and
    ``is_conservative`` marks fallback values used when a probe failed or timed
    out.
    """

    model_set_hash: str
    measured_backbone_vram_mb: int
    estimated_worker_ram_mb: int
    gpu_capable: bool
    is_conservative: bool = False


@dataclass(frozen=True, slots=True)
class ModelVramLimit:
    """Measured or corrected VRAM budget for one model.

    ``limit_bytes`` is the peak VRAM budget associated with ``model_path`` in
    bytes. The ``sys.maxsize`` sentinel represents a model marked GPU-incompatible
    by the probe.
    """

    model_path: str
    limit_bytes: int


@dataclass(frozen=True, slots=True)
class GpuResourceSnapshot:
    """A point-in-time snapshot of GPU resource availability.

    ``gpu_available`` records whether the GPU is usable and ``error_summary``
    describes any probe failure (``None`` when the GPU is healthy).
    """

    gpu_available: bool
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class LockEntry:
    """A distributed-lock state exposed by the application persistence facade.

    Callers address a lock by its logical type and resource, and receive its
    ownership and lifecycle state.  The physical key/value representation used
    by the PostgreSQL repository is deliberately not part of this domain type.
    """

    lock_type: str
    resource_id: str
    holder: str
    expires_at: float
    acquired_at: float
    status: str


@dataclass(frozen=True, slots=True)
class VramPromise:
    """GPU memory reservation owned by one worker and model.

    The worker/model pair is the domain identity.  Persistence-generated
    identifiers and the ``vram_promises`` table are intentionally absent from
    this contract.
    """

    worker_id: str
    pid: int
    model_path: str
    promised_mb: float
    total_mb: float
    used_mb: float


@dataclass(frozen=True, slots=True)
class WorkerRestartPolicy:
    """Restart history and failure state for one worker component.

    This is the domain contract exposed by ``AppDb``.  Persistence details such
    as the JSONB ``policy_data`` column are deliberately hidden from callers.
    """

    restart_count: int = 0
    last_restart_wall_ms: int | None = None
    failed_at_wall_ms: int | None = None
    failure_reason: str | None = None
    updated_at_wall_ms: int | None = None


__all__ = [
    "CapacityEstimate",
    "ConfigOption",
    "GpuResourceSnapshot",
    "LockEntry",
    "ModelVramLimit",
    "VramPromise",
    "WorkerRestartPolicy",
]
