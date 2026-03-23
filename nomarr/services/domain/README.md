# Domain Services

Service classes that expose domain operations to the interface layer. Each service owns DI wiring, receives `Database` via constructor, and delegates business logic to workflows and components.

## Responsibilities

- Provide the public API surface consumed by interface endpoints
- Own dependency injection (accept `Database`, config, and peer services)
- Delegate multi-step orchestration to workflows
- Translate between interface DTOs and internal domain types

## Key Modules

| Module | Purpose |
|--------|---------|
| `analytics_svc.py` | Tag frequency, mood distribution, co-occurrence, and collection overview analytics |
| `calibration_svc.py` | Histogram calibration generation, convergence tracking, background threading |
| `metadata_svc.py` | Entity (tag) navigation — list, get, song-entity relationships, orphan cleanup |
| `navidrome_svc.py` | Navidrome integration — config generation, smart/static playlists, sync, scrobbles |
| `playlist_import_svc.py` | Spotify/Deezer playlist conversion to local M3U via track matching |
| `tagging_svc.py` | Calibrated tag application — file/library tagging, reconciliation, background apply |
| `vector_maintenance_svc.py` | Hot→cold vector promotion, index rebuild, stats |
| `vector_search_svc.py` | ANN similarity search against cold vector collections |
| `_library_mapping.py` | DTO mapper — converts raw file dicts to `LibraryFileWithTags` DTOs |
| `library_svc/` | Composite library service (admin, scan, query, files, entities) — see subfolder README |

## Patterns

- **Config dataclasses**: Each service has a companion `*Config` dataclass for static settings
- **Background threading**: `CalibrationService` and `TaggingService` use background threads with thread-safe progress reporting
- **Service composition**: `NavidromeService` reads credentials live from `ConfigService` so web UI changes take effect without restart

## Architecture Rules

> **Services MUST NOT call persistence directly.** All database access flows through workflows and components which accept `Database` as a parameter.

## Dependencies

- **Called by**: `interfaces/api/web/` endpoints via FastAPI DI
- **Calls**: `workflows/*` for orchestration, `components/*` for domain logic
- **Receives**: `Database`, `ConfigService`, peer domain services via constructor injection
