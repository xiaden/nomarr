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
- **DI via Depends**: All services injected through `dependencies.py` providers

## Dependencies

- **Calls**: All domain and infrastructure services via `Depends()`
- **MUST NOT** import or access persistence directly
- **Imports**: `api/types/` for response models, `api/auth.py` for auth guards

