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

    embeddings: Any  # np.ndarray
    sample_rate: int
    num_segments: int
