# Data Transfer Objects

Typed dataclasses and TypedDicts shared across all layers — the canonical data contracts between services, workflows, and components.

## Responsibilities

- Define immutable, typed data containers for cross-layer communication
- Provide domain-specific DTOs grouped by feature area
- Export all public types via `__init__.py` (39 exports)

## Key Modules

 | Module | Purpose |
 | -------- | -------- |
 | `admin_dto.py` | `JobRemovalResult`, `WorkerOperationResult`, `RunCalibrationResult`, `RetagAllResult` |
 | `analytics_dto.py` | `TagCoOccurrenceData`, `TagCorrelationData`, `MoodDistributionData` |
 | `calibration_dto.py` | Calibration run parameters and result containers |
 | `config_dto.py` | `ProcessorConfig` — ML processing configuration passed through layers |
 | `health_dto.py` | `ComponentPolicy`, `ComponentStatus`, `StatusChangeContext`, `ComponentLifecycleHandler` |
 | `info_dto.py` | System info aggregation types |
 | `library_dto.py` | `LibraryPath`, `LibraryDict`, `SearchFilesResult`, `StartScanResult`, `WriteTagsResult` (largest — 14 types) |
 | `metadata_dto.py` | Entity cleanup and metadata seeding types |
 | `ml_dto.py` | `LoadAudioMonoResult`, `AnalyzeWithSegmentsResult`, `SingleHeadResult`, `ProcessHeadPredictionsResult` |
 | `navidrome_dto.py` | `NdSyncResult`, `TasteProfile`, `TasteCluster`, `NavidromePersonalPlaylistContext` |
 | `path_dto.py` | `LibraryPath` — validated file path with status tracking |
 | `playlist_import_dto.py` | `PlaylistMetadata`, `PlaylistTrackInput`, `MatchResult`, `PlaylistConversionResult` |
 | `processing_dto.py` | `ProcessFileResult` — single-file processing outcome |
 | `recalibration_dto.py` | Recalibration workflow parameters and results |
 | `tagging_dto.py` | `TagWriteProfile`, `TagSpec`, `TagCondition` — tag write and filter types |
 | `tags_dto.py` | `Tag`, `Tags`, `TagValue` — core tag data model (frozen, sorted, tuple-based) |
 | `vector_config_dto.py` | `VectorConfigResult` — per-library vector configuration with inheritance |

## Patterns

- **Frozen dataclasses**: Most DTOs use `@dataclass(frozen=True)` for immutability
- **TypedDicts for DB shapes**: `LibraryDict`, `ReconcileResult` use `TypedDict` when matching DB document shapes
- **Always-tuple invariant**: `Tags.value` is always a tuple, eliminating scalar/list branching
- **No business logic**: DTOs are pure data — no methods beyond `from_dict()` / `to_dict()` convenience

## Dependencies

- **No `nomarr.*` imports**: DTOs must not import from any other nomarr layer
- **Used by**: every layer (interfaces, services, workflows, components, persistence)
- **External**: only stdlib and typing imports
