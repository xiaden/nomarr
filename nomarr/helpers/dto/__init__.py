"""
Domain-specific DTOs (Data Transfer Objects) used across multiple layers.

Domain-specific DTOs live in helpers/dto/<domain>.py and form cross-layer contracts
within that domain (interfaces → services → workflows → components).

helpers/dataclasses.py is reserved for truly cross-domain dataclasses shared by
multiple domains.

Architecture:
- helpers/dto/<domain>.py: Domain-specific DTOs (e.g., Navidrome, processing, analytics)
- helpers/dataclasses.py: Cross-domain dataclasses used by multiple domains
- Both are safe to import from all layers (interfaces, services, workflows, components)

Rules for DTO modules:
- Import only stdlib and typing (no nomarr.* imports)
- Contain ONLY dataclass/type definitions and simple type aliases
- No I/O, no DB access, no business logic
- Pure data structures with optional simple properties

Dataclass Classification:
- Category A (Cross-layer DTOs): Moved to helpers/dto/<domain>.py
  * Analytics: TagCorrelationData, MoodDistributionData, ArtistTagProfile, MoodCoOccurrenceData
  * Navidrome: PlaylistPreviewResult, SmartPlaylistFilter, TagCondition
  * Processing: ProcessorConfig, TagWriteProfile

- Category B (Service-local config): Kept in service modules
  * NavidromeConfig, CoordinatorConfig, LibraryRootConfig, WorkerConfig, MLConfig,
    HealthMonitorConfig, CalibrationConfig, AnalyticsConfig

- Category C (Component-internal helpers): Kept in component modules
  * ML: HeadOutput, HeadSpec, Cascade, Segments
  * Paths: LibraryPath (unused)
"""

from __future__ import annotations

from nomarr.helpers.dto.analytics import (
    ArtistTagProfile,
    MoodCoOccurrenceData,
    MoodDistributionData,
    TagCorrelationData,
)
from nomarr.helpers.dto.ml import (
    AnalyzeWithSegmentsResult,
    ComputeEmbeddingsForBackboneParams,
    GenerateMinmaxCalibrationResult,
    LoadAudioMonoResult,
    SaveCalibrationSidecarsResult,
    SegmentWaveformParams,
)
from nomarr.helpers.dto.navidrome import (
    PlaylistPreviewResult,
    SmartPlaylistFilter,
    TagCondition,
)
from nomarr.helpers.dto.processing import ProcessorConfig, TagWriteProfile

__all__ = [
    "ArtistTagProfile",
    "MoodCoOccurrenceData",
    "MoodDistributionData",
    "PlaylistPreviewResult",
    "ProcessorConfig",
    "SmartPlaylistFilter",
    "TagCondition",
    "TagCorrelationData",
    "TagWriteProfile",
]
