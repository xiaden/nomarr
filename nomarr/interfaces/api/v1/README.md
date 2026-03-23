# Versioned Public API (v1)

Versioned routes for external integrations — Navidrome plugin, admin automation, and public info.

## Responsibilities

- Expose stable, versioned endpoints under `/api/v1/` for third-party consumers
- Provide Navidrome integration endpoints (similar tracks, scrobbles, playlist generation)
- Expose admin automation routes (worker control, calibration triggers)
- Serve public system info without authentication

## Key Modules

| Module | Purpose |
|--------|--------|
| `admin_if.py` | Worker pause/resume, calibration trigger (3 endpoints) |
| `navidrome_v1_if.py` | Similar tracks via ANN search, scrobble ingestion, playlist generation (3 endpoints) |
| `public_if.py` | Unauthenticated system info endpoint (1 endpoint) |

## Patterns

- **Versioned prefix**: All routes mount under `/api/v1/` — breaking changes require a new version
- **Request/response models**: Navidrome endpoints define inline Pydantic models (`SimilarTracksRequest`, `ScrobbleRequest`, etc.) alongside the route handlers
- **Service delegation**: Every handler receives its service via `Depends()` and delegates immediately

## Dependencies

- **Calls**: `NavidromeService`, `CalibrationService`, `ConfigService`, `WorkerSystemService`, `InfoService`
- **MUST NOT** import or access persistence directly
- **Imports**: `web/dependencies.py` for DI providers
