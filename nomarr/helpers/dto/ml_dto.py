"""
ML domain DTOs.

Data transfer objects for ML components, inference, and calibration.
These form cross-layer contracts between components, workflows, and services.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HeadOutput:
    """
    In-memory representation of a head's output with tier information.

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

    head: Any  # HeadInfo from components - use Any to avoid circular import
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
    path: str
    min_duration_s: int
    allow_short: bool


@dataclass
class SegmentWaveformParams:
    """Parameters for segment_waveform."""

    y: Any  # np.ndarray
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
