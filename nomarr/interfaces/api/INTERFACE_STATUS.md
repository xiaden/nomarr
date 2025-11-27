# API Interface Migration Status

This document tracks the migration of all API endpoints to use DTO-backed Pydantic models.

## Architecture Pattern

All API domains follow this pattern:
- **DTOs** (helpers/dto/**_dto.py): Pure dataclasses, internal contracts between layers
- **Pydantic Models** (interfaces/api/types/**_types.py): External API contracts with .from_dto() / .to_dto()
- **Route Handlers** (interfaces/api/web/**_if.py): Thin adapters that parse requests, call services, transform responses

```
Request Flow:  JSON → Pydantic Request → .to_dto() → Service (accepts DTO) → ...
Response Flow: ... → Service (returns DTO) → .from_dto() → Pydantic Response → JSON
```

## Migration Status

### ✅ Fully Migrated Domains

These domains follow the DTO-backed Pydantic pattern:

| Domain | Types File | Route File | DTOs |
|--------|-----------|------------|------|
| **Queue** | `types/queue_types.py` | `web/queue_if.py` | `dto/queue_dto.py` (EnqueueFilesResult, ListJobsResult, QueueStatusResult, etc.) |
| **Library** | `types/library_types.py` | `web/library_if.py` | `dto/library_dto.py` (LibraryDict, LibraryStatsResult, LibraryScanStatusResult, etc.) |
| **Processing** | `types/processing_types.py` | `web/processing_if.py` | `dto/processing_dto.py` (ProcessFileResult, ProcessorConfig, TagWriteProfile, WorkerStatusResult, etc.) |
| **Navidrome** | `types/navidrome_types.py` | `web/navidrome_if.py` | `dto/navidrome_dto.py` (PlaylistPreviewResult, SmartPlaylistFilter, PreviewTagStatsResult, etc.) |

### ⏳ Pending Migration

These domains need to be migrated to use DTO-backed Pydantic models:

| Domain | Route File | Current State | DTOs Available | Notes |
|--------|-----------|---------------|----------------|-------|
| **Analytics** | `web/analytics_if.py` | Uses TypedDict, returns dicts | `dto/analytics_dto.py` (TagCorrelationData, MoodDistributionData, MoodCoOccurrenceData, ArtistTagProfile) | 4 endpoints need migration |
| **Calibration** | `web/calibration_if.py` | Pydantic requests, dict responses | `dto/calibration_dto.py` (GenerateCalibrationResult, EnsureCalibrationsExistResult, CalibrationRunResult, RecalibrateFileWorkflowParams) | 4 endpoints need migration |
| **Config** | `web/config_if.py` | Pydantic request, dict responses | `dto/config_dto.py` (ConfigResult, GetInternalInfoResult) | 2 endpoints need migration |
| **Auth** | `web/auth_if.py` | Already uses Pydantic request/response | No DTOs (simple auth flow) | ✅ Already clean (no DTOs needed) |
| **Info/Health** | `web/info_if.py` | Returns dicts | No specific DTOs (system status) | Simple status endpoints, may not need formal DTOs |
| **Tags** | `web/tags_if.py` | Returns dicts | No DTOs (direct file tag reading) | Direct file access, may not need DTOs |
| **SSE** | `web/sse_if.py` | SSE streaming | No DTOs (event streaming) | Server-sent events, different pattern |
| **FS** | `web/fs_if.py` | File system browsing | No DTOs (filesystem operations) | Direct filesystem ops, may not need DTOs |

### 🎯 Migration Priority

**High Priority** (have DTOs, need Pydantic wrappers):
1. **Analytics** - 4 endpoints, clear DTOs available
2. **Calibration** - 4 endpoints, clear DTOs available  
3. **Config** - 2 endpoints, clear DTOs available

**Low Priority** (simple or no DTOs needed):
4. **Info/Health** - Simple status, consider if DTOs add value
5. **Tags** - Direct file reading, may not benefit from DTOs
6. **FS** - Filesystem browsing, may not benefit from DTOs
7. **SSE** - Event streaming, different pattern
8. **Auth** - Already clean, no changes needed

## Next Steps

1. Migrate **Analytics** domain:
   - Create `interfaces/api/types/analytics_types.py`
   - Add Pydantic response models with .from_dto() for all DTOs
   - Update `web/analytics_if.py` endpoints to return Pydantic models

2. Migrate **Calibration** domain:
   - Create `interfaces/api/types/calibration_types.py`
   - Add Pydantic response models with .from_dto()
   - Update `web/calibration_if.py` endpoints

3. Migrate **Config** domain:
   - Create `interfaces/api/types/config_types.py`
   - Add Pydantic response models with .from_dto()
   - Update `web/config_if.py` endpoints

4. Evaluate low-priority domains for whether formal DTOs/Pydantic models add value
