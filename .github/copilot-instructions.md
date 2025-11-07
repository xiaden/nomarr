## Nomarr — Copilot Instructions

This file captures concise, actionable knowledge for coding agents to be productive in this repository.

- Quick entry points:
  - `readme.md` — canonical overview, Docker/Lidarr setup, cache semantics, CLI vs API behavior, and links to deeper docs.
  - `docs/NAMING_STANDARDS.md` — **CRITICAL**: Naming conventions for variables, functions, database columns, API fields. Review before adding new code.
  - `docs/API_REFERENCE.md` — endpoint details, schemas, and Lidarr integration examples.
  - `docs/NAVIDROME_INTEGRATION.md` — Navidrome custom tags config, Smart Playlist syntax, integration workflow. Reference when building playlist/tag export features.
  - `nomarr/interfaces/api/app.py` — FastAPI app + lifecycle, shared TaggerWorker, auth, endpoints.
  - `nomarr/interfaces/cli/main.py` — CLI command dispatcher.
  - `nomarr/core/processor.py` — Core audio processing pipeline (domain logic).
  - `nomarr/services/` — Business operations (ProcessingService, QueueService, LibraryService, WorkerService, HealthMonitor, analytics, Navidrome integration).
  - `nomarr/data/` — `db.py` (SQLite), `queue.py` (JobQueue + TaggerWorker).
  - `nomarr/ml/models/` — `discovery.py`, `embed.py`, `heads.py`, `writers.py` (ML model interfaces).
  - `nomarr/ml/` — `inference.py` (ML inference), `cache.py` (model cache).
  - `nomarr/tagging/` — `aggregation.py` (tag processing rules).
  - `config/config.yaml` — runtime config; container-mounted at `/app/config/config.yaml` and loaded by `compose()`.
  - `models/` — sidecars (`.json`) + graphs (`.pb`); both required.
  - `scripts/generate_inits.py` — auto-generate `__init__.py` files with proper `__all__` exports (run after adding/removing public classes/functions).

- Development tools:
  - `ruff` — linter and formatter (**RUN AFTER MAJOR CHANGES**: `ruff check .` then `ruff check --fix .`)
  - `scripts/discover_api.py` — **MANDATORY before writing tests**: Shows actual module API (classes, methods, signatures)
  - `scripts/check_naming.py` — detect naming convention violations (optional)
  - `scripts/generate_inits.py` — auto-generate `__init__.py` files; run with `python scripts/generate_inits.py` after adding/removing/renaming public exports

- Codebase structure (semantic layered architecture):
  ```
  nomarr/
  ├── interfaces/          # Presentation layer (all user-facing code)
  │   ├── api/            # FastAPI HTTP (public + internal + web endpoints, auth, models, helpers, coordinator, event_broker, state)
  │   ├── cli/            # Terminal CLI (commands, main.py dispatcher, ui.py with Rich components, utils)
  │   └── web/            # Browser-based web UI (HTML/CSS/JS, session-based auth)
  ├── services/           # Business operations & orchestration
  │   ├── processing.py   # ProcessingService (wraps ProcessingCoordinator, enforces fail-fast)
  │   ├── queue.py        # QueueService (job queue operations)
  │   ├── library.py      # LibraryService (library file queries, tag operations)
  │   ├── worker.py       # WorkerService (worker state management)
  │   ├── health.py       # HealthMonitor (worker health tracking)
  │   ├── analytics.py    # Tag analysis functions (frequencies, correlations, mood distributions)
  │   ├── workers/        # Worker implementations
  │   │   └── scanner.py  # LibraryScanWorker (background library scanning)
  │   └── navidrome/      # Navidrome integration (config + playlist generation)
  ├── core/               # Core domain logic (essential processing pipeline)
  │   ├── processor.py    # process_file() - main audio processing orchestration
  │   └── library_scanner.py  # scan_library(), update_library_file_from_tags()
  ├── ml/                 # Machine learning (isolated namespace)
  │   ├── inference.py    # ML model inference engine
  │   ├── cache.py        # Model cache management
  │   └── models/         # ML model interfaces
  │       ├── discovery.py    # Model discovery and metadata
  │       ├── embed.py        # Embedding models
  │       ├── heads.py        # Classification head models
  │       └── writers.py      # Model-to-tag writers
  ├── tagging/            # Tag processing rules
  │   └── aggregation.py  # aggregate_mood_tiers(), mood aggregation logic
  ├── data/               # Persistence layer
  │   ├── db.py           # Database (SQLite schema, queries)
  │   └── queue.py        # JobQueue, TaggerWorker (queue worker)
  ├── helpers/            # Shared utilities
  │   └── (various helpers)
  └── (root modules)      # config.py, rules.py, start_api.py
  ```

- High-level architecture (how pieces communicate):
  - **Single unified API** (0.0.0.0:8356) serves public endpoints (for Lidarr), internal endpoints (for CLI), and web endpoints (for browser UI).
  - **Three-layer authentication**:
    - Public endpoints (`/tag`, `/queue`, etc.) use `api_key` authentication (for Lidarr/webhooks)
    - Internal endpoints (`/internal/*`) use separate `internal_key` (for CLI, auto-generated and hidden)
    - Web endpoints (`/web/*`, `/web/api/*`) use session tokens from admin password login (for browser UI)
  - Web UI uses server-side proxy architecture: browser → session token → `/web/api/*` → server-side proxy → `/internal/*` with `internal_key` (never exposed to browser)
  - Admin password: auto-generated on first run, stored as salted SHA-256 hash in DB, managed via `manage_password.py` CLI
  - Sessions: write-through cache (in-memory for performance, DB for persistence), 24-hour expiry, survives container restarts
  - API + TaggerWorker + LibraryScanWorker share a single SQLite DB (`config/db/essentia.sqlite`). The DB stores queue rows, library files, library scans, meta (api_key, internal_key, admin_password_hash, worker_enabled, averages), results, session tokens.
  - API starts on container boot via `start_api.py`. Model cache is **lazy-loaded** (models cached on first use, not at startup).
  - **TaggerWorker**: Polls DB for pending tag jobs and calls `core/processor.py:process_file()`; DB mutations are under `queue.lock`. Long-running work happens outside the lock.
  - **LibraryScanWorker**: Background thread (in `services/workers/scanner.py`) that scans music library directory, reads all tags from audio files, and updates `library_files` table. Configured via `library_path` in config.yaml. Runs independently from tagging operations.
  - **CLI requires internal API** to be running. Uses `/internal/process_stream` for instant processing with warm cache and real-time streaming progress.
  - **Web UI requires internal API** to be running. Uses `/web/api/*` proxy endpoints that call `/internal/*` server-side. Includes Library tab for managing library scans.
  - **Multi-worker parallelism**: ProcessingCoordinator (in `interfaces/api/coordinator.py`) uses ProcessPoolExecutor with configurable worker_count (default 1). Each worker process loads independent model cache (~400MB per worker). Note: Multiple workers can overwhelm consumer GPUs; adjust carefully.
  - **GPU concurrency**: TensorFlow configured via environment variables (`TF_FORCE_GPU_ALLOW_GROWTH=true`, `TF_GPU_THREAD_MODE=gpu_private`) to enable multiple worker processes to use GPU simultaneously without pre-allocating all VRAM.
  - **Service layer**: All business operations go through services (ProcessingService, QueueService, LibraryService, WorkerService, HealthMonitor). Services provide fail-fast behavior and proper error handling.

- Important repository-specific conventions and patterns:
  - Tag namespace: all tags are written under `essentia:<key>` (config `namespace`).
  - Emit-all scores: multilabel/multiclass heads write base probabilities for all labels; tiers only for selected labels.
  - Mood aggregation: `mood-strict`, `mood-regular`, `mood-loose` are native multi-value tags derived from `*_tier` tags. Mood terms come from head names (spaces or underscores handled). Per-model probabilities are available via individual label keys.
  - DB concurrency: use `queue.lock` for DB mutations; do not hold the lock during file processing.
  - Worker state via DB meta `worker_enabled` (and `config.yaml` defaults). Admin endpoints toggle the worker.
  - API auth: API key in DB meta; enforced by `HTTPBearer`.
  - Blocking: `blocking_mode`/`blocking_timeout` control `/tag` behavior. Defaults: blocking with a single timeout.
  - Poll interval: prefer `poll_interval` (worker). Deprecated aliases are still accepted but may warn.
  - **CLI commands**: Available commands are `run`, `queue`, `list`, `remove`, `info`, `show-tags`, `cleanup`, `cache-refresh`, `admin-reset`, `watch`. The `admin-reset` command has `--stuck` and `--errors` flags to target specific job states.

- Data shapes and contracts (quick reference):
  - POST /api/v1/tag: { path: string, force?: boolean } (public API, queues job)
  - GET /api/v1/list?limit=50&offset=0&status=pending: list jobs with pagination and filtering (recommended)
  - GET /api/v1/queue?limit=5: legacy job listing (use /list instead)
  - POST /internal/process_direct: { path: string, force?: boolean } (internal API, synchronous)
  - POST /internal/process_stream: { path: string, force?: boolean } (internal API, SSE streaming with real-time progress)
  - POST /internal/batch_process: { paths: string[], force?: boolean } (internal API, multiple files)
  - POST /web/auth/login: { password: string } (web API, returns session token)
  - POST /web/auth/logout: (web API, invalidates session)
  - POST /web/api/process: { path: string, force?: boolean } (web API proxy, SSE streaming)
  - POST /web/api/batch-process: { paths: string[], force?: boolean } (web API proxy)
  - GET /web/api/list?limit=50&offset=0&status=pending: (web API proxy for job listing)
  - POST /web/api/queue/remove: { job_id: number } (web API proxy)
  - POST /web/api/admin/worker/pause: (web API proxy)
  - Job lifecycle: `pending` → `running` → `done|error`
  - Queue/admin: `/list`, `/queue`, `/status/{id}`, `/admin/queue/*`, `/admin/cache/refresh`
  - Errors: 404 (missing files), 403 (auth), 409 (invalid ops), 503 (no workers available)
  - SSE events: `progress` (head updates), `complete` (result), `error`, `done` (stream end)

- Integration and operational notes (useful for fixes/features):
  - Models live under `/app/models`; ensure both `.json` and `.pb` exist for each head/embedding.
  - API keys: `python3 -m nomarr.manage_key --show` (public key). Internal key is auto-generated and stored in DB.
  - Admin password: `python3 -m nomarr.manage_password --show` (view), `--verify` (check), `--reset` (change). Auto-generated on first run and logged to container output.
  - Quick smoke test: `python3 -m nomarr.interfaces.cli.main run /music/TestSong.mp3` (requires internal API running).
  - Web UI access: Navigate to `http://<server>:8356/` and log in with admin password.
  - Temporarily pause worker: `/admin/worker/pause`; resume: `/admin/worker/resume`.
  - Refresh model cache after adding/removing models: `/admin/cache/refresh` or CLI `cache-refresh` command.
  - All endpoints (public + internal + web) are on port 8356; different auth per layer.

- Small decisions to respect when changing behavior:
  - Never process audio while holding the DB lock.
  - Maintain backward-compatible config keys (flat + legacy nested aliases).
  - Preserve tag format and namespace; do not change key naming schemes lightly.
  - Do not create additional worker loops; the single `TaggerWorker` is authoritative.
  - GPU environment variables (`TF_FORCE_GPU_ALLOW_GROWTH`, `TF_GPU_THREAD_MODE`) must be set before Essentia imports in `core/processor.py`.
  - Worker slot cleanup must happen in `finally` blocks to prevent stuck "No workers available" errors.
  - SSE streaming endpoints must poll event queues while futures run (not after completion) for real-time updates.
  - After adding/removing/renaming public classes or functions, run `python scripts/generate_inits.py` to update `__init__.py` files.
  - Services enforce fail-fast: ProcessingService raises RuntimeError if ProcessingCoordinator unavailable (no silent fallbacks).

- Useful files to open for context when implementing a change:
  - `nomarr/interfaces/api/app.py` — unified API (public + internal + web endpoints), worker lifecycle
  - `nomarr/interfaces/api/auth.py` — authentication logic (API keys, admin password hashing, session management)
  - `nomarr/interfaces/api/endpoints/web.py` — web UI endpoints (login/logout, proxy endpoints)
  - `nomarr/interfaces/web/` — browser UI files (app.js, index.html, styles.css)
  - `nomarr/start_api.py` — single-process API launcher
  - `nomarr/manage_password.py` — admin password CLI tool
  - `nomarr/interfaces/cli/main.py` — internal API client with local fallback
  - `nomarr/core/processor.py` — orchestration of model inference and tag writing
  - `nomarr/services/processing.py` — ProcessingService (wraps coordinator, fail-fast)
  - `nomarr/services/queue.py` — QueueService (job queue operations)
  - `nomarr/services/library.py` — LibraryService (library file queries)
  - `nomarr/services/worker.py` — WorkerService (worker state)
  - `nomarr/services/health.py` — HealthMonitor (worker health)
  - `nomarr/services/analytics.py` — tag analysis functions
  - `nomarr/services/navidrome/` — Navidrome integration
  - `nomarr/ml/inference.py` — ML model inference engine
  - `nomarr/ml/cache.py` — model cache management
  - `nomarr/ml/models/` — ML model interfaces (discovery, embed, heads, writers)
  - `nomarr/tagging/aggregation.py` — mood aggregation logic
  - `nomarr/data/queue.py` / `nomarr/data/db.py` — queue locking and DB schema
  - `readme.md` — deployment, Docker Compose example and workflows

If anything here is unclear or you want the instructions to include run/debug commands for Windows devs or unit-test notes, tell me which details to add and I will iterate.

---

Development & Deployment Architecture

- **Development**: Code is developed on Windows (PowerShell environment).
- **Deployment**: Docker container is built and run on a separate Ubuntu server.
- **Workflow**: Make changes locally on Windows, commit/push, then rebuild container on Ubuntu server.
- **Testing**: Cannot use `docker compose build` locally during development - container must be rebuilt on deployment server.

---

Docker & Lidarr sideloading (Ubuntu server notes)

- Purpose: this project is intended to run as a Docker sidecar alongside Lidarr so imported files (on shared volumes) can be tagged in-place.

- Networking & compose:
  - Prefer a Docker Compose service in the same Docker network as Lidarr. Example service name `nomarr` is reachable by `http://nomarr:8356` from Lidarr when both are in the same compose network.
  - Keep the default container port internal; no host port needs to be exposed when accessed from the same Docker network.

- Volumes and permissions (critical):
  - Mount your music library into the container at the same absolute path Lidarr uses (e.g., `/music`). Use a consistent mapping: host:/music -> container:/music.
  - The container must be able to write audio files and the SQLite DB file. Ensure UID/GID used by the container matches or has write permission to the host-mounted paths. The existing `docker-compose` snippet uses `user: "1000:1000"` for this reason.
  - The SQLite DB should be persisted on a volume: e.g., host `./config` -> container `/app/config` so `config/db/essentia.sqlite` survives restarts.

- Lidarr integration (post-import):
  - Use a post-import script (Lidarr's custom script or webhook) to call the tagger. Example cURL (from Lidarr server or from an entrypoint container on same network):

    curl -X POST \
      -H "Authorization: Bearer <API_KEY>" \
      -H "Content-Type: application/json" \
      -d '{"path":"/music/Album/Track.mp3"}' \
      http://nomarr:8356/api/v1/tag

  - If Lidarr runs on the host (not in the same docker network), call the container using the host IP and an exposed port, or create a docker network that both services join.

- API key & testing inside container:
  - The API key is persisted in DB meta. To show or regenerate it inside the container:

    python3 -m nomarr.manage_key --show
    python3 -m nomarr.manage_key --generate

  - Quick smoke test inside the running container:

    python3 -m nomarr.interfaces.cli.main run /music/TestSong.mp3

- Common deployment checklist for Ubuntu servers:
  1. Install Docker + Docker Compose (compose V2 CLI recommended).
  2. Ensure host directories exist and are owned/writable by the container user (or use `user:` in compose to match host UID/GID).
  3. Place models under `./models` and config under `./config` (which contains `db/essentia.sqlite`).
  4. Start the service with `docker compose up -d` and confirm logs with `docker compose logs -f nomarr`.

- Troubleshooting & recovery tips:
  - If files are not being written, check file-system permissions first (container can read but not write).
  - Check `docker compose logs nomarr` for exceptions from `core/processor.py` or worker messages in `interfaces/api/app.py`.
  - To temporarily stop automatic processing: set `worker_enabled: false` in `config/config.yaml` (or `/admin/worker/pause`) and use CLI `run` for debugging.
  - To remove stuck jobs: Use CLI `remove --all` or `remove --status error`. Admin endpoints also support removal by job ID.
  - If CLI warnings/errors aren't visible, ensure the ProgressDisplay logging bridge remains attached during runs (see `interfaces/cli/ui.py`).
  - **GPU utilization issues**: Low GPU usage (~3%) with multiple workers suggests sequential processing. Verify `TF_FORCE_GPU_ALLOW_GROWTH=true` is set in `core/processor.py`. Check `nvidia-smi` for multiple processes using GPU. Sequential model loading is normal (disk I/O bottleneck on first file per worker).
  - **"No workers available" errors**: Worker slots are released when processing completes or on client disconnect. If slots don't release, check API logs for `Released worker X` messages. Use CLI `admin-reset --stuck` to reset jobs stuck in "running" state.
  - **Ctrl+C behavior**: Canceling CLI commands closes the stream but lets background processing complete (prevents file corruption). Worker slots release when API detects closed connection. Re-running immediately should work.
  - **ProcessingService errors**: If you see "ProcessingCoordinator is not available", the API may not have initialized properly. Check API startup logs for coordinator initialization errors. Services fail-fast rather than degrading silently.

---

## MANDATORY Development Workflows (For AI Agents)

### Before Writing Tests or Using Any Module

**ALWAYS run API discovery first** to see what actually exists:

```bash
# Discover module API before writing tests or using functions
python scripts/discover_api.py nomarr.data.db
python scripts/discover_api.py nomarr.data.queue
python scripts/discover_api.py nomarr.interfaces.api.auth

# Quick summary (just class/function names)
python scripts/discover_api.py nomarr.data.queue --summary
```

**DO NOT:**
- ❌ Guess at function names (`add_job` vs `add`, `get_job` vs `get`)
- ❌ Assume class structures (`SessionManager` when it's just functions)
- ❌ Write tests without discovering actual signatures first

**DO:**
- ✅ Run `discover_api.py` to see actual method names and signatures
- ✅ Copy exact signatures from discovery output
- ✅ Verify parameter names match before using

### After Major Changes or at Checkpoints

**ALWAYS run linters** to check code quality:

```bash
# Python: Check for issues
ruff check .

# Python: Auto-fix what's possible
ruff check --fix .

# Python: Format code
ruff format .

# JavaScript: Check web UI code
npm run lint

# JavaScript: Auto-fix formatting
npm run lint:fix
```

**Run linters after:**
- Creating new files
- Major refactors (like error_text → error_message)
- Adding multiple functions/classes
- Before committing changes
- When you see linter warnings

### Development Cycle (Standard Flow)

1. **Discover API** → `python scripts/discover_api.py <module>`
2. **Write/modify code** using discovered API
3. **Check quality** → `ruff check .`
4. **Fix issues** → `ruff check --fix .`
5. **Run tests** → `pytest tests/`
6. **Check naming** → `python scripts/check_naming.py` (optional)

This prevents the cycle of:
- Guess API → Write test → Test fails → Fix test → Repeat 10 times ❌

Instead:
- Discover API → Write correct test → Test passes → Done ✅
