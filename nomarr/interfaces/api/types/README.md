# API Type Definitions

Pydantic request and response models for all API endpoints.

## Responsibilities

- Define strongly-typed HTTP request bodies and response schemas
- Provide `from_dto()` class methods to convert service-layer DTOs to API responses
- Export all types via `__init__.py` for clean imports

## Key Modules

 | Module | Purpose |
 | -------- | -------- |
 | `analytics_types.py` | Tag frequencies, mood distribution, correlations, collection overview |
 | `api_key_types.py` | API key management requests/responses |
 | `config_types.py` | Config read/update requests and responses |
 | `info_types.py` | System info, health status, GPU health, models info |
 | `library_types.py` | Library CRUD, scan, search, file tags, reconciliation |
 | `metadata_types.py` | Entity counts, entity list/detail responses |
 | `ml_types.py` | ML model listing, output labels, VRAM probe |
 | `navidrome_types.py` | Navidrome config, playlist generation, template management |
 | `playlist_import_types.py` | Spotify/Deezer playlist import, preview, smart filters |
 | `processing_types.py` | File processing requests and batch results |
 | `vector_types.py` | Vector search, promote, rebuild, stats responses |

## Patterns

- **DTO → Response**: Types use `@classmethod from_dto()` to convert internal DTOs, keeping serialization at the boundary
- **Flat hierarchy**: One file per domain — mirrors the `web/` endpoint file structure
- **No business logic**: Types are pure data containers with optional validation

## Dependencies

- **Imports**: `helpers/dto` for DTO classes used in `from_dto()` converters
- **MUST NOT** import services, components, or persistence
