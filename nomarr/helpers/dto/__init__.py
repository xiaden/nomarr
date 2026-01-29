"""Domain-specific DTOs (Data Transfer Objects) used across multiple layers.

Domain-specific DTOs live in helpers/dto/<domain>_dto.py and form cross-layer contracts
within that domain (interfaces → services → workflows → components).

helpers/dataclasses.py is reserved for truly cross-domain dataclasses shared by
multiple domains.

Architecture:
- helpers/dto/<domain>_dto.py: Domain-specific DTOs (e.g., Navidrome, processing, analytics)
- helpers/dataclasses.py: Cross-domain dataclasses used by multiple domains
- Both are safe to import from all layers (interfaces, services, workflows, components)

Rules for DTO modules:
- Import only stdlib and typing (no nomarr.* imports)
- Contain ONLY dataclass/type definitions and simple type aliases
- No I/O, no DB access, no business logic
- Pure data structures with optional simple properties

Dataclass Classification:
- Category A (Cross-layer DTOs): Moved to helpers/dto/<domain>_dto.py
  * Analytics: TagCorrelationData, MoodDistributionData, ArtistTagProfile, MoodCoOccurrenceData
  * Navidrome: PlaylistPreviewResult, SmartPlaylistFilter, TagCondition
  * Processing: ProcessorConfig, TagWriteProfile

- Category B (Service-local config): Kept in service modules
  * NavidromeConfig, CoordinatorConfig, LibraryServiceConfig, MLConfig,
    HealthMonitorConfig, CalibrationConfig, AnalyticsConfig

- Category C (Component-internal helpers): Kept in component modules
  * ML: HeadOutput, HeadSpec, Cascade, Segments
"""

from __future__ import annotations

from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    MoodDistributionData,
    TagCoOccurrenceData,
    TagCorrelationData,
    TagSpec,
)
from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentPolicy,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.helpers.dto.library_dto import ScanTarget
from nomarr.helpers.dto.ml_dto import (
    AnalyzeWithSegmentsResult,
    ComputeEmbeddingsForBackboneParams,
    GenerateMinmaxCalibrationResult,
    LoadAudioMonoResult,
    SaveCalibrationSidecarsResult,
    SegmentWaveformParams,
)
from nomarr.helpers.dto.navidrome_dto import (
    PlaylistPreviewResult,
    SmartPlaylistFilter,
    TagCondition,
)
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.helpers.dto.processing_dto import (
    ProcessFileResult,
    ProcessorConfig,
    TagWriteProfile,
)
from nomarr.helpers.dto.tags_dto import Tag, Tags, TagValue

__all__ = [
    "AnalyzeWithSegmentsResult",
    "ArtistTagProfile",
    "ComponentLifecycleHandler",
    "ComponentPolicy",
    "ComponentStatus",
    "ComputeEmbeddingsForBackboneParams",
    "GenerateMinmaxCalibrationResult",
    "LibraryPath",
    "LoadAudioMonoResult",
    "MoodDistributionData",
    "PlaylistPreviewResult",
    "ProcessFileResult",
    "ProcessorConfig",
    "SaveCalibrationSidecarsResult",
    "ScanTarget",
    "SegmentWaveformParams",
    "SmartPlaylistFilter",
    "StatusChangeContext",
    "Tag",
    "TagCoOccurrenceData",
    "TagCondition",
    "TagCorrelationData",
    "TagSpec",
    "TagValue",
    "TagWriteProfile",
    "Tags",
]
