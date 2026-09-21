"""Info domain DTOs.

Data transfer objects for system info and health status endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


@dataclass
class SystemInfoResult:
    """Result from get_system_info service method."""

    version: str
    namespace: str
    models_dir: str
    worker_enabled: bool
    worker_count: int


@dataclass
class HealthStatusResult:
    """Result from get_health_status service method."""

    status: str
    processor_initialized: bool
    worker_count: int
    queue: dict[str, Any]
    warnings: list[str]


@dataclass
class GPUHealthResult:
    """Result from get_gpu_health service method.

    Contains GPU resource snapshot and monitor liveness.
    Monitor liveness is determined by HealthMonitorService, not DB.
    """

    available: bool
    error_summary: str | None
    monitor_healthy: bool = False  # True if GPUHealthMonitor subprocess is alive


# ----------------------------------------------------------------------
#  Public Info DTOs (for public API endpoint)
# ----------------------------------------------------------------------


@dataclass
class ConfigInfo:
    """Configuration information for public info endpoint."""

    db_path: str | None
    models_dir: str
    namespace: str
    api_host: str | None
    api_port: int | None
    worker_enabled: bool
    worker_enabled_default: bool
    worker_count: int
    poll_interval: float


@dataclass
class ModelsInfo:
    """Models information for public info endpoint."""

    total_heads: int
    embeddings: list[str]


@dataclass
class QueueInfo:
    """Queue information for public info endpoint."""

    depth: int
    counts: dict[str, int]


@dataclass
class WorkerInfo:
    """Worker information for public info endpoint."""

    enabled: bool
    alive: bool
    last_heartbeat: float | None


@dataclass
class PublicInfoResult:
    """Complete public info result from get_public_info."""

    config: ConfigInfo
    models: ModelsInfo
    queue: QueueInfo
    worker: WorkerInfo


# ----------------------------------------------------------------------
#  Work Status DTOs
# ----------------------------------------------------------------------


@dataclass
class ScanningLibraryInfo:
    """Info about a library currently being scanned.

    ``library_id`` is the natural library name (mechanism A).
    """

    library_id: str
    name: str
    progress: int
    total: int


WriteRequestedMode = Literal["none", "files", "database"]
WriteEvidenceClass = Literal["fingerprint_same", "fingerprint_different", "fingerprint_indeterminate"]
WriteOutcomeStatus = Literal[
    "active",
    "written",
    "partial",
    "not_written",
    "cancelled",
    "conflict",
    "indeterminate",
    "raced",
    "failed",
    "replacement",
    "deferred",
    "unavailable",
    "evicted",
]
RecoveryAction = Literal[
    "none",
    "manual_reconciliation",
    "retry",
    "adopt_database_metadata",
    "project_database_to_files",
    "replacement_reimport_requeue",
    "deferred_retry",
    "refresh_status",
]


class SelectedRunCounts(TypedDict, total=False):
    """Counts belonging to the selected write run, never global pending work."""

    selected: int
    processed: int
    failed: int
    remaining: int
    modified_external: int
    refreshed_database: int
    overwritten_files: int
    raced: int
    cancelled: int
    deferred: int
    unavailable: int


@dataclass
class LibraryPipelineInfo:
    """Per-library pipeline and recovery status for work-status polling."""

    library_id: str
    name: str
    state: str
    library_auto_write: bool
    write_outcome: str | None = None
    scan_state: str | None = None
    hydration_state: str | None = None
    hydration_count: int | None = None
    tag_write_state: str | None = None
    requested_mode: WriteRequestedMode | None = None
    selected_run_counts: SelectedRunCounts | None = None
    outcome: WriteOutcomeStatus | None = None
    evidence_class: WriteEvidenceClass | None = None
    resumable: bool | None = None
    recovery_action: RecoveryAction | None = None
    message_code: str | None = None


@dataclass
class WorkStatusResult:
    """Result from get_work_status service method.

    Unified work status for the system: scanning, processing, tagging.
    """

    # Scanning status
    is_scanning: bool
    scanning_libraries: list[ScanningLibraryInfo]
    pipeline_libraries: list[LibraryPipelineInfo]

    # ML processing status (files needing tagging)
    is_processing: bool
    pending_files: int
    processed_files: int
    total_files: int

    # Velocity (computed from last 5 minutes of actual processing)
    files_per_minute: float
    estimated_minutes_remaining: float | None

    # Overall activity indicator — True while any pipeline stage is active
    # (scanning, ML processing, calibration, or tag writing) or work is pending.
    is_busy: bool
