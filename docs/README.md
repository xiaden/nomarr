# Documentation Index

This folder centralizes documentation for Essentia Autotag.

## Main Documentation

- **Getting Started** (canonical): `../readme.md`
- **API Reference**: `API_REFERENCE.md` - Endpoint documentation, schemas, Lidarr integration
- **Deployment Guide**: `DEPLOYMENT.md` - Docker setup, configuration
- **Model Reference**: `modelsinfo.md` - Essentia models documentation (upstream reference)
- **Model Wiring Validation**: `MODEL_WIRING_VALIDATION.md` - Model validation notes

## Architecture Overview

```
essentia_autotag/
├── interfaces/          # Presentation layer (all user-facing code)
│   ├── api/            # FastAPI HTTP (public + internal + web endpoints, auth, coordinator, event_broker, state)
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
└── (shared utilities)  # config.py, util.py, rules.py, helpers/
```

## Authentication Architecture

Nomarr uses a **three-layer authentication system**:

1. **Public API** (Lidarr/webhooks):
   - Endpoints: `/tag`, `/queue`, `/status`, `/admin/*`
   - Auth: `api_key` (Bearer token)
   - Use case: External automation, Lidarr post-import hooks

2. **Internal API** (CLI):
   - Endpoints: `/internal/process_stream`, `/internal/process_direct`, `/internal/batch_process`, `/internal/health`
   - Auth: `internal_key` (auto-generated, stored in DB)
   - Use case: CLI commands with warm cache and real-time streaming

3. **Web UI** (browser):
   - Endpoints: `/web/auth/login`, `/web/auth/logout`, `/web/api/*` (proxy endpoints)
   - Auth: Session token (24-hour expiry) obtained via admin password login
   - Use case: Browser-based monitoring and control
   - Security: Server-side proxy to internal API (never exposes `internal_key` to browser)

**Security model:**
- `api_key`: User-managed, shown via `manage_key.py --show`, used for external integrations
- `internal_key`: Auto-generated at startup, hidden from users, used for CLI ↔ API communication
- `admin_password`: User-managed via `manage_password.py`, used for web UI login, stored as salted SHA-256 hash
- Session tokens: Write-through cache (in-memory for performance + DB for persistence), 24-hour lifetime, survives container restarts

## Key Conventions

- **Single unified API** on port 8356 with public (`/tag`), internal (`/internal/*`), and web (`/web/*`) endpoints
- **API key auth**: Public endpoints use `api_key`, internal endpoints use `internal_key`, web endpoints use session tokens
- **Cache warmup**: Predictor cache loaded at startup, refreshed via `/admin/cache/refresh`
- **Tag namespace**: All tags written under `essentia:` prefix
- **Mood aggregation**: `mood-strict`, `mood-regular`, `mood-loose` are native multi-value tags
- **DB concurrency**: Lock acquired only for mutations, never during file processing
