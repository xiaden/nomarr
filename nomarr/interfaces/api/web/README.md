# Web Dashboard API Endpoints

Internal HTTP endpoints powering the Nomarr web dashboard.

## Responsibilities

- Expose CRUD and action endpoints for every dashboard feature
- Wire FastAPI dependency injection to service layer singletons
- Route registration via central router module

## Key Modules

 | Module | Purpose |
 | -------- | -------- |
 | `router.py` | Registers all endpoint routers into the FastAPI app |
 | `dependencies.py` | FastAPI `Depends()` providers for services |
 | `admin_if.py` | Server restart |
 | `analytics_if.py` | Tag frequencies, mood distribution, correlations, collection overview |
 | `api_key_if.py` | API key get/regenerate |
 | `auth_if.py` | Login, logout, session management |
 | `calibration_if.py` | Calibration clear/start/status, histogram generation |
 | `config_if.py` | Read/update global configuration |
 | `fs_if.py` | Filesystem browser for library path selection |
 | `info_if.py` | System info, health, GPU health |
 | `library_if.py` | Library CRUD, stats, vector stats (per-library) |
 | `songs_if.py` | File search, tag search, tag key/value listing, file tags, errored files |
 | `library_scan_if.py` | Library scan (quick/full), repair, reconcile, write tags, pipeline status |
 | `metadata_if.py` | Entity listing, detail, songs-by-entity, artists-for-album, albums-for-artist |
 | `ml_if.py` | Model listing, output labels, configuration, VRAM probe, work status, recent activity |
 | `navidrome_if.py` | Navidrome preview, config, playlists, templates, personal playlists |
 | `playlist_import_if.py` | Spotify/Deezer playlist import, credential status |
 | `tag_curation_if.py` | Tag rename, merge, split, list values, commit pending, update file tags |
 | `tags_if.py` | Show/remove tags from audio files |
 | `vectors_if.py` | Vector search, track vector, stats, promote, rebuild index |

## Patterns

- **One file per domain**: Each `*_if.py` file groups related endpoints (mirrors `types/` structure)
- **Thin handlers**: Endpoints decode IDs, call one service method, encode response — no business logic
- **Lifecycle conflicts**: Quick/full scan and write-tag actions return HTTP `409 Conflict` with structured detail when the library is scanning, writing, or has hydration debt. The detail contains `code`, `operation`, `scan_state`, `tag_write_state`, and `not_hydrated_count`; clients should retry after the reported lifecycle work completes. Admission is serialized per parent library, and hydration/refresh operations are guarded while tag writing is active. An admitted write-tag request returns HTTP `202 Accepted` with a background task ID.
- **Write-tag contract**: `POST /api/web/library/{library_name}/write-tag` accepts an optional strict JSON body containing only `overwrite`, whose values are `none` (default), `files`, or `database`. The response contains `status`, `task_id`, `requested_mode`, and `outcome`. `files` permits same-fingerprint external-file rebaselining and retry; `database` refreshes database metadata for that same-fingerprint case; `none` applies no recovery override.
- **Work-status contract**: `GET /api/web/machine-learning/work-status` returns overall polling fields plus `pipeline_libraries`. Each library projection exposes normalized `scan_state`, `hydration_state`, `hydration_count`, `tag_write_state`, `requested_mode`, `selected_run_counts`, `outcome`, `evidence_class`, `resumable`, `recovery_action`, and `message_code` fields (alongside compatibility `state` and `write_outcome`). Outcomes include `active`, `written`, `partial`, `not_written`, `cancelled`, `conflict`, `indeterminate`, `raced`, `failed`, `replacement`, `deferred`, `unavailable`, and `evicted`; evidence classes are `fingerprint_same`, `fingerprint_different`, and `fingerprint_indeterminate`. Recovery actions include `none`, `manual_reconciliation`, `retry`, `adopt_database_metadata`, `project_database_to_files`, `replacement_reimport_requeue`, `deferred_retry`, and `refresh_status`.
- **DI via Depends**: All services injected through `dependencies.py` providers

## Dependencies

- **Calls**: All domain and infrastructure services via `Depends()`
- **MUST NOT** import or access persistence directly
- **Imports**: `api/types/` for response models, `api/auth.py` for auth guards

