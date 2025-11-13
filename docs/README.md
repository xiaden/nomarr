# Documentation Index

This folder centralizes documentation for Nomarr.

## Main Documentation

- **Getting Started** (canonical): `../readme.md`
- **API Reference**: `API_REFERENCE.md` - Endpoint documentation, schemas, Lidarr integration
- **Deployment Guide**: `DEPLOYMENT.md` - Docker setup, configuration
- **Model Reference**: `modelsinfo.md` - Essentia models documentation (upstream reference)
- **Model Wiring Validation**: `MODEL_WIRING_VALIDATION.md` - Model validation notes

## Architecture Overview

```
nomarr/
├── interfaces/          # Presentation layer (all user-facing code)
│   ├── api/            # FastAPI HTTP (public + admin + web endpoints, auth, coordinator, event_broker, state)
│   ├── cli/            # Rich terminal CLI (commands, UI components, utils)
│   └── web/            # Browser-based web UI (HTML/CSS/JS, session-based auth)
├── services/           # Business operations & orchestration
│   ├── processing.py   # ProcessingService (wraps coordinator, fail-fast)
│   ├── queue.py        # QueueService (job queue operations)
│   ├── library.py      # LibraryService (library file queries)
│   ├── worker.py       # WorkerService (worker state management)
│   ├── health.py       # HealthMonitor (worker health tracking)
│   ├── analytics.py    # Tag analysis functions
│   ├── workers/        # Worker implementations (scanner.py)
│   └── navidrome/      # Navidrome integration
├── core/               # Core domain logic (essential processing pipeline)
│   ├── processor.py    # Main audio processing orchestration
│   └── library_scanner.py  # Library scanning operations
├── ml/                 # Machine learning (isolated namespace)
│   ├── inference.py    # ML model inference engine
│   ├── cache.py        # Model cache management
│   └── models/         # Model interfaces (discovery, embed, heads, writers)
├── tagging/            # Tag processing rules (aggregation.py)
├── data/               # Persistence layer (db.py, queue.py)
└── (shared utilities)  # config.py, rules.py, helpers/, app.py, start.py
```

## Authentication Architecture

Nomarr uses a **two-layer authentication system**:

1. **Public/Admin API** (Lidarr/webhooks/management):

   - Endpoints: `/api/v1/tag`, `/api/v1/queue`, `/api/v1/status`, `/admin/*`
   - Auth: `api_key` (Bearer token)
   - Use case: External automation, Lidarr post-import hooks, queue/worker management

2. **Web UI** (browser):
   - Endpoints: `/web/auth/login`, `/web/auth/logout`, `/web/api/*`
   - Auth: Session token (24-hour expiry) obtained via admin password login
   - Use case: Browser-based monitoring and control

**CLI Architecture:**

- CLI accesses Application services directly (no HTTP endpoints)
- No authentication needed (runs in same process as API server)
- Direct access to model cache and services

**Security model:**

- `api_key`: User-managed, shown via `manage_key.py --show`, used for external integrations
- `admin_password`: User-managed via `manage_password.py`, used for web UI login, stored as salted SHA-256 hash
- Session tokens: Write-through cache (in-memory + DB), 24-hour lifetime, survive container restarts

## Key Conventions

- **Single unified API** on port 8356 with public (`/api/v1/*`), admin (`/admin/*`), and web (`/web/*`) endpoints
- **API key auth**: Public/admin endpoints use `api_key`, web endpoints use session tokens
- **Cache strategy**: Models lazy-loaded on first use, refreshed via `/admin/cache/refresh`
- **Tag namespace**: All tags written under `essentia:` prefix
- **Mood aggregation**: `mood-strict`, `mood-regular`, `mood-loose` are native multi-value tags
- **DB concurrency**: Lock acquired only for mutations, never during file processing
