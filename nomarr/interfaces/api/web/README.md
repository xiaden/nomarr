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
 | `dependencies.py` | FastAPI `Depends()` providers for 15 services |
 | `analytics_if.py` | Tag frequencies, mood distribution, correlations, collection overview |
 | `api_key_if.py` | API key create/list/revoke |
 | `auth_if.py` | Login, logout, session management |
 | `calibration_if.py` | Calibration run, history, apply, recalibration status |
 | `config_if.py` | Read/update global configuration |
 | `fs_if.py` | Filesystem browser for library path selection |
 | `info_if.py` | System info, health, queue status, worker status |
 | `library_if.py` | Library CRUD, scan, search, tags, reconciliation, vector config (largest) |
 | `metadata_if.py` | Entity listing, detail, cleanup |
 | `ml_if.py` | Model listing, output labels, configuration, VRAM probe |
 | `navidrome_if.py` | Navidrome sync, playlists, templates, crawl |
 | `playlist_import_if.py` | Spotify/Deezer import, preview, smart playlist filters |
 | `processing_if.py` | File processing, batch processing |
 | `tags_if.py` | Show/remove tags from audio files |
 | `vectors_if.py` | Vector search, promote, rebuild index, stats |
 | `worker_if.py` | Worker status, pause/resume, job listing |

## Patterns

- **One file per domain**: Each `*_if.py` file groups related endpoints (mirrors `types/` structure)
- **Thin handlers**: Endpoints decode IDs, call one service method, encode response — no business logic
- **DI via Depends**: All services injected through `dependencies.py` providers

## Dependencies

- **Calls**: All domain and infrastructure services via `Depends()`
- **MUST NOT** import or access persistence directly
- **Imports**: `api/types/` for response models, `api/auth.py` for auth guards
