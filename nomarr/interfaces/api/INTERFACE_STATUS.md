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
 | -------- | ----------- | ------------ | ------ |
 | **Library** | `types/library_types.py` | `web/library_if.py` | `dto/library_dto.py` (LibraryDict, LibraryStatsResult, LibraryScanStatusResult, etc.) |
 | **Library Scan** | `types/library_types.py` | `web/library_scan_if.py` | `dto/library_dto.py` (ReconcileResult, StartScanResult, etc.) |
 | **Library Files** | `types/library_types.py` | `web/songs_if.py` | `dto/library_dto.py` (SearchFilesResult, FileTagsResult, etc.) |
 | **Navidrome** | `types/navidrome_types.py` | `web/navidrome_if.py` | `dto/navidrome_dto.py` (PlaylistPreviewResult, SmartPlaylistFilter, PreviewTagStatsResult, etc.) |
 | **Analytics** | `types/analytics_types.py` | `web/analytics_if.py` | `dto/analytics_dto.py` (TagCorrelationData, MoodDistributionData, etc.) |
 | **Config** | `types/config_types.py` | `web/config_if.py` | `dto/config_dto.py` (ConfigResult, GetInternalInfoResult) |
 | **Info** | `types/info_types.py` | `web/info_if.py` | `dto/info_dto.py` (SystemInfoResult, HealthStatusResult, etc.) |
 | **Metadata** | `types/metadata_types.py` | `web/metadata_if.py` | `dto/metadata_dto.py` (EntityDict, EntityListResult, etc.) |
 | **ML** | `types/ml_types.py` | `web/ml_if.py` | `dto/ml_dto.py` / `dto/ml_head_dto.py` |
 | **Playlist Import** | `types/playlist_import_types.py` | `web/playlist_import_if.py` | `dto/playlist_import_dto.py` |
 | **Vectors** | `types/vector_types.py` | `web/vectors_if.py` | `dto/vector_config_dto.py` |
 | **Tag Curation** | N/A (returns dicts) | `web/tag_curation_if.py` | `dto/tag_curation_dto.py` (RenameResult, MergeResult, etc.) |
 | **Navidrome v1** | `v1/navidrome_v1_if.py` (inline models) | `v1/navidrome_v1_if.py` | `dto/navidrome_dto.py` |

### ⏳ Pending Migration

These domains have partial or pending migration to use DTO-backed Pydantic models:

 | Domain | Route File | Current State | DTOs Available | Notes |
 | -------- | ----------- | --------------- | ---------------- | ------- |
 | **Calibration** | `web/calibration_if.py` | Pydantic requests via TypedDict responses, dict responses | `dto/calibration_dto.py` (GenerateCalibrationResult, EnsureCalibrationsExistResult, etc.) | Responses use TypedDict (``ApplyCalibrationCombinedStatusDict``, ``HistogramGenerationCombinedStatusDict``) — should be Pydantic |
 | **Auth** | `web/auth_if.py` | Already uses Pydantic request/response | No DTOs (simple auth flow) | ✅ Already clean (no DTOs needed) |
 | **Tags** | `web/tags_if.py` | Returns dicts | No DTOs (direct file tag reading) | Direct file access, may not need DTOs |
 | **FS** | `web/fs_if.py` | File system browsing | No DTOs (filesystem operations) | Direct filesystem ops, may not need DTOs |
 | **API Key** | `web/api_key_if.py` | Dict responses | No DTOs (returns simple key) | Simple endpoints, may not need formal DTOs |
 | **Admin** | `web/admin_if.py` | Pydantic response | No DTOs (restart only) | ✅ Already clean |

### ❌ Removed / Deprecated Domains

These domains previously existed but have been removed or their routes folded into other handlers:

 | Domain | Reason |
 | -------- | -------- |
 | **Queue** (`types/queue_types.py`, `web/queue_if.py`) | Queue management removed with discovery-based worker system; processing state now managed via ``file_states`` graph edges |
 | **Processing** (`web/processing_if.py`) | Processing routes folded into library workflow; ML-related routes moved to ``web/ml_if.py`` |
 | **SSE** (`web/sse_if.py`) | Server-sent events streaming removed |
 | **Worker** (`web/worker_if.py`) | Worker management removed; replaced by discovery-based worker system |

### 🎯 Migration Priority

**High Priority** (remaining work):

1. **Calibration** - Responses currently use TypedDict types; migrate to Pydantic response models

**Low Priority** (simple or no DTOs needed):
2. **Tags** - Direct file reading, may not benefit from DTOs
3. **FS** - Filesystem browsing, may not benefit from DTOs
4. **API Key** - Simple key response, may not need formal DTOs
5. **Auth** - Already clean, no changes needed
6. **Admin** - Already clean, no changes needed

## Next Steps

1. Migrate **Calibration** domain response models:
   - Replace ``ApplyCalibrationCombinedStatusDict`` and ``HistogramGenerationCombinedStatusDict`` TypedDict types with Pydantic response models in ``types/``
   - Update ``web/calibration_if.py`` endpoints to return proper Pydantic models

2. Evaluate remaining low-priority domains for whether formal DTOs/Pydantic models add value
