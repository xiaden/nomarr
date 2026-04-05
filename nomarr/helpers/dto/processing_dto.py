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

from nomarr.helpers.dto.ml_edge_dto import MLEdgeWrites

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

    Contains values fixed at startup: model paths, internal constants,
    and tagger versioning. Created once by ConfigService.make_processor_config()
    and serialized to worker subprocesses at spawn time.

    These fields never change at runtime. User-changeable processing settings
    (calibrate_heads) are read live from
    ConfigService by each consuming service at use time.
    """

    # Path to models directory containing embeddings and heads
    models_dir: str

    # Minimum audio duration in seconds
    min_duration_s: int

    # Allow processing files shorter than min_duration_s
    allow_short: bool

    # Batch size for head prediction (VRAM control)
    batch_size: int

    # Tag namespace (e.g., "essentia")
    namespace: str

    # Key name for the version tag
    version_tag_key: str

    # Current tagger version string
    tagger_version: str

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
class DeferredFileWrites:
    """DB write payloads collected during ML processing.

    Returned by ``process_file_workflow`` so the caller can execute writes
    asynchronously (e.g. on a background thread) while the ML loop continues
    with the next file.

    The expected execution order is:
    1. ``save_file_tags``   (tag vertices + edges)
    2. write ``tag_model_output`` edges via ``ml_edges``
    3. ``set_chromaprint``  (fingerprint)
    4. compute segment stats from raw_segments (deferred from hot path)
    5. ``upsert_stats``     (segment statistics)
    6. ``mark_file_tagged`` (only if 1-5 succeeded)
    7. ``release_claim``    (always, even on error)
    """

    file_id: str
    path: str
    db_tags: dict[str, Any]
    namespace: str
    tagger_version: str
    chromaprint: str | None
    raw_segments: dict[str, tuple[Any, list[str]]]  # head_name -> (segment_scores ndarray, labels)
    ml_edges: MLEdgeWrites | None = None


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
    timing_summary: str | None = None
    deferred_writes: DeferredFileWrites | None = None
