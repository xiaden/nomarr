"""ML domain DTOs.

Data transfer objects for ML components, inference, and calibration.
These form cross-layer contracts between components, workflows, and services.

Rules:
- Import only stdlib and typing at runtime (TYPE_CHECKING-guarded nomarr.* imports are permitted for type annotations)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.components.ml.onnx.ml_discovery_comp import HeadInfo
    from nomarr.components.ml.onnx.ml_head import ONNXHeadModel
    from nomarr.helpers.dto.path_dto import LibraryPath


@dataclass
class HeadOutput:
    """In-memory representation of a head's output with tier information.

    Tier is computed using calibration (if available) but never persisted
    as a *_tier tag. It's only used for mood aggregation and conflict resolution.

    Attributes:
        head: The HeadInfo that produced this output
        model_key: Versioned tag key (no calibration suffix)
        label: Label name (e.g., "happy", "mainstream")
        value: Numeric score (post-calibration if applied)
        tier: Tier level ("low", "medium", "high", etc.) - internal only
        calibration_id: Which calibration was applied (e.g., "none_0", "platt_1")

    """

    head: HeadInfo | ONNXHeadModel
    model_key: str
    label: str
    value: float
    tier: str | None = None
    calibration_id: str | None = None


@dataclass
class LoadAudioMonoResult:
    """Result from load_audio_mono."""

    waveform: Any  # np.ndarray, but we can't import numpy here
    sample_rate: int
    duration: float


@dataclass
class GenerateMinmaxCalibrationResult:
    """Result from generate_minmax_calibration."""

    method: str
    library_size: int
    min_samples: int
    calibrations: dict[str, Any]
    skipped_tags: int


@dataclass
class SaveCalibrationSidecarsResult:
    """Result from save_calibration_sidecars."""

    saved_files: dict[str, dict[str, Any]]  # path -> {labels: list, label_count: int}
    total_files: int
    total_labels: int


@dataclass
class ComputeEmbeddingsForBackboneParams:
    """Parameters for compute_embeddings_for_backbone."""

    backbone: str
    emb_graph: str
    target_sr: int
    segment_s: float
    hop_s: float
    path: LibraryPath  # Security boundary: must be factory-built LibraryPath
    min_duration_s: int
    allow_short: bool
    prefer_gpu: bool = True  # GPU/CPU adaptive: False forces CPU execution
    pre_loaded_audio: LoadAudioMonoResult | None = None  # Skip audio loading if provided
    pre_computed_chromaprint: str | None = (
        None  # Skip chromaprint if provided  # GPU/CPU adaptive: False forces CPU execution
    )


@dataclass
class SegmentWaveformParams:
    """Parameters for segment_waveform."""

    waveform: Any  # np.ndarray
    sr: int
    segment_s: float
    hop_s: float
    pad_final: bool


@dataclass
class AnalyzeWithSegmentsResult:
    """Result from analyze_with_segments."""

    pooled_vector: Any  # np.ndarray - pooled embedding vector
    segments: Any  # Segments object with waves and bounds
    duration: float  # audio duration in seconds


@dataclass
class ProcessHeadPredictionsResult:
    """Result from running all heads for a single backbone."""

    heads_succeeded: int
    head_results: dict[str, Any]
    regression_heads: list[tuple[Any, list[float]]]
    all_head_outputs: list[Any]
    raw_segments_per_head: dict[str, tuple[Any, list[str]]]  # head -> (scores, labels)
    per_head_timings: dict[str, float]  # head_name -> duration_ms


@dataclass
class SingleHeadResult:
    """Result from processing a single head (thread-safe, no shared mutation)."""

    head_name: str
    status: str  # "success", "error_processing", "error_aggregation"
    error: str | None = None
    head_tags: dict[str, Any] | None = None
    head_outputs: list[Any] | None = None
    regression_data: tuple[Any, list[float]] | None = None
    raw_segment_scores: Any | None = None  # np.ndarray — deferred to async write thread
    segment_labels: list[str] | None = None  # labels for segment stats computation
    elapsed_ms: float = 0.0
    decisions_count: int = 0
