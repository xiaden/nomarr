"""Processing domain DTOs.

Data transfer objects for audio processing configuration and tag writing.
These form cross-layer contracts between interfaces, services, and workflows.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nomarr.helpers.dto.tags_dto import Tags


@dataclass
class TagWriteProfile:
    """Controls what tags are written to media files vs stored only in DB.

    Similar to a logging level - allows configuration-driven control over
    tag verbosity in media files.

    Attributes:
        file_write_mode: Controls tag writing to media files:
            - "none": No tags written to files (DB only)
            - "minimal": Only high-level summary tags (mood-*, genre, etc.)
            - "full": Rich tag set including numeric scores (but never *_tier or calibration)

    """

    file_write_mode: Literal["none", "minimal", "full"] = "minimal"


@dataclass
class ResourceManagementConfig:
    """Configuration for GPU/CPU adaptive resource management.

    Per GPU_REFACTOR_PLAN.md Section 13:
    - enabled: Whether resource management is active
    - vram_budget_mb: Maximum VRAM ML may consume (absolute MB)
    - ram_budget_mb: Maximum RAM ML may consume (absolute MB)
    - ram_detection_mode: How to detect RAM usage (auto/cgroup/host)
    """

    enabled: bool = True
    vram_budget_mb: int = 12288  # 12GB default
    ram_budget_mb: int = 16384  # 16GB default
    ram_detection_mode: Literal["auto", "cgroup", "host"] = "auto"


@dataclass
class ProcessorConfig:
    """Configuration for the audio processing pipeline.

    All fields are required to ensure explicit configuration.
    Validation should happen at the service layer when constructing this.
    """

    # Path to models directory containing embeddings and heads
    models_dir: str

    # Minimum audio duration in seconds
    min_duration_s: int

    # Allow processing files shorter than min_duration_s
    allow_short: bool

    # Batch size for head prediction (VRAM control)
    batch_size: int

    # Whether to overwrite existing tags
    overwrite_tags: bool

    # Tag namespace (e.g., "essentia")
    namespace: str

    # Key name for the version tag
    version_tag_key: str

    # Current tagger version string
    tagger_version: str

    # Whether to load calibration files
    calibrate_heads: bool

    # File write mode: controls what tags go to media files
    file_write_mode: Literal["none", "minimal", "full"] = "minimal"

    # Resource management configuration (GPU/CPU adaptive)
    resource_management: ResourceManagementConfig | None = None


@dataclass
class WorkerEnabledResult:
    """Result from worker_service pause_workers/resume_workers."""

    worker_enabled: bool


@dataclass
class WorkerStatusResult:
    """Result from worker_service.get_status/pause/resume."""

    enabled: bool
    worker_count: int
    running: int
    workers: list[dict[str, Any]]


@dataclass
class ProcessFileResult:
    """Result from process_file_workflow."""

    file_path: str
    elapsed: float
    duration: float | None
    heads_processed: int
    tags_written: int
    head_results: dict[str, dict[str, Any]]
    mood_aggregations: dict[str, int] | None
    tags: Tags
