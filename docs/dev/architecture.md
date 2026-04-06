# Architecture Overview

**Audience:** Developers working on Nomarr or understanding its design principles.

Nomarr follows Clean Architecture principles with strict dependency direction rules, dependency injection, and clear separation of concerns across layers.

---

## Core Principles

### 1. Dependency Direction

Dependencies flow **inward** from interfaces to domain logic:

```
interfaces → services → workflows → components → persistence/helpers
```

**Rules:**
- Outer layers depend on inner layers, never reverse
- Inner layers have no knowledge of outer layers
- Business logic is isolated from transport mechanisms (HTTP, CLI)
- `import-linter` enforces these boundaries in CI

### 2. Dependency Injection

No global state or singleton imports. Major resources (database, config, ML backends) are injected via constructor parameters or FastAPI `Depends`.

**Constructor injection (services):**
```python
class WorkerSystemService:
    def __init__(
        self,
        db: Database,
        processor_config: ProcessorConfig,
        health_monitor: HealthMonitorService | None = None,
        worker_count: int = 1,
    ) -> None:
        self.db = db
        self.processor_config = processor_config
        ...
```

**FastAPI Depends (interfaces):**
```python
@router.post("/scan")
async def scan_library(
    request: ScanRequest,
    library_svc: LibraryService = Depends(get_library_service),
) -> ScanResponse:
    result = library_svc.scan.start_scan(request.library_id)
    return ScanResponse.from_dto(result)
```

### 3. Pure Workflows

Workflows orchestrate domain logic by composing components. All dependencies are received as parameters.

```python
def process_file_workflow(
    db: Database,
    file_doc: dict,
    processor_config: ProcessorConfig,
    backbone_session: OnnxBackboneSession,
    head_sessions: dict[str, OnnxHeadSession],
) -> ProcessFileResult:
    # 1. Load and preprocess audio
    audio = ml_audio_comp.load_mono(file_doc["path"], target_sr)
    mel = ml_preprocess_comp.compute_mel(audio, target_sr)
    # 2. Run backbone embedding
    embeddings = ml_backbone_embed_comp.embed(backbone_session, mel)
    # 3. Run head inference
    predictions = ml_head_pipeline_comp.run_heads(head_sessions, embeddings)
    # 4. Write tags
    tagging_writer_comp.write_tags(file_doc["path"], predictions)
    ...
```

### 4. Persistence via Components Only

Only components may call persistence methods (`db.*`) directly. Services and workflows may hold a `Database` reference for DI wiring and pass-through, but never invoke persistence operations themselves. Interfaces never access persistence at all.

```python
# ✅ GOOD — Component accesses persistence and enforces invariants
# components/library/file_library_comp.py
def add_file(db: Database, library_id: str, file_path: str) -> dict:
    library = db.libraries.get(library_id)
    if not is_under_root(file_path, library["root_path"]):
        raise ValueError("Path not under library root")
    return db.library_files.insert({"path": file_path, ...})

# ✅ GOOD — Workflow calls component
# workflows/library/scan_library_full_wf.py
from nomarr.components.library.file_library_comp import add_file

def scan_library_workflow(db, library_id):
    for path in discovered:
        add_file(db, library_id, path)

# ❌ BAD — Workflow accessing persistence directly
db.library_files.insert({"path": path})  # Bypasses invariants!
```

### 5. ONNX Inference Backend

All ML inference runs exclusively through ONNX Runtime.

- **Backbone models** (e.g., effnet) produce audio embeddings via `components/ml/onnx/ml_backbone.py`
- **Head models** (e.g., genre, mood) produce predictions via `components/ml/onnx/ml_head.py`
- **Session management** via `components/ml/onnx/ml_session_comp.py` with VRAM-aware caching
- **Essentia** is used only for audio I/O (`ml_audio_comp.py`) and mel spectrogram preprocessing (`ml_preprocess_comp.py`) — it is **not** the ML backend

---

## Layer Responsibilities

### Interfaces (`interfaces/`)

**Purpose:** Expose Nomarr to external consumers (HTTP API, CLI).

**Contains:**
- `api/web/` — FastAPI HTTP endpoints (authenticated UI API)
- `api/v1/` — Public/external API endpoints
- `api/types/` — Pydantic request/response models
- `cli/` — Command-line interface

**Rules:**
- Validate inputs (Pydantic handles this)
- Call exactly **one service method** per endpoint
- Serialize outputs
- **No business logic, no direct database access, no ML inference**

**Example:**
```python
@router.post("/process")
async def process_files(
    request: ProcessRequest,
    tagging_svc: TaggingService = Depends(get_tagging_service),
) -> ProcessResponse:
    result = tagging_svc.process_files(request.paths)
    return ProcessResponse.from_dto(result)
```

---

### Services (`services/`)

**Contains:**
- `domain/` — Library, analytics, calibration, metadata, navidrome, tagging, vector search/maintenance, playlist import
- `infrastructure/` — Config, workers, health monitor, pipeline orchestration, ML, file watcher, background tasks, CLI bootstrap

**Purpose:** Own runtime resources, wire dependencies, orchestrate workflows.

**Rules:**
- Construct long-lived objects (Database, workers, ML sessions)
- Inject dependencies into workflows
- Return DTOs to interfaces
- **No HTTP/CLI knowledge, minimal logic**
- Services may call workflows and/or components directly (workflows are not mandatory pass-through for simple operations)

**Example:**
```python
class TaggingService:
    def __init__(self, db: Database, ml_svc: MLService):
        self.db = db
        self.ml_svc = ml_svc

    def process_files(self, paths: list[str]) -> ProcessResult:
        return process_file_workflow(
            db=self.db,
            paths=paths,
            processor_config=self.ml_svc.processor_config,
        )
```

---

### Workflows (`workflows/`)

**Purpose:** Implement multi-step use cases by composing components.

**Contains:**
- `calibration/` — Calibration generation, application, import/export
- `library/` — Scanning, sync, cleanup, tag I/O, path reconciliation
- `metadata/` — Entity cleanup, cache rebuild
- `navidrome/` — Playlist generation, smart playlists, sync, scrobble
- `platform/` — Database preparation, migrations, vector index operations
- `playlist_import/` — External playlist conversion
- `processing/` — File processing, tag writing
- `vectors/` — Track vector retrieval

**Rules:**
- Accept all dependencies as parameters
- Call components (and other workflows) — **never import services or interfaces**
- **No global config reads**

---

### Components (`components/`)

**Purpose:** Domain-specific logic. The only layer that may access persistence.

**Contains:**
- `analytics/` — Tag statistics, collection overview, mood analysis
- `infrastructure/` — Health, path resolution
- `library/` — File management, scanning, move detection, search, metadata extraction
- `metadata/` — Entity seeding, cleanup, caching
- `ml/` — Audio loading, preprocessing, ONNX inference, calibration, vectors, resource management
- `navidrome/` — Subsonic client, playlist builder, templates, taste profiles
- `platform/` — ArangoDB bootstrap, GPU monitoring, migration runner
- `playlist_import/` — Spotify/Deezer fetchers, track matching, URL parsing
- `processing/` — File write operations
- `tagging/` — Tag parsing, normalization, aggregation, reading/writing
- `workers/` — Crash recovery, work discovery

**Rules:**
- Implement complex domain logic
- Can call persistence and helpers
- **No knowledge of services, workflows, or interfaces**

---

### Persistence (`persistence/`)

**Purpose:** ArangoDB access layer.

**Contains:**
- `db.py` — `Database` facade class
- `database/` — One `*Operations` class per collection (or collection group)

**Access pattern:** Always through the `Database` facade, never importing Operations classes directly.

```python
# ✅ Via Database facade
db = Database()
claimed = db.worker_claims.try_claim_file(file_id, worker_id)

# ❌ Direct import
from nomarr.persistence.database.worker_claims_aql import WorkerClaimsOperations
```

**Key collections (via `db.*`):**

| Accessor | Collection(s) | Domain |
|----------|---------------|--------|
| `db.libraries` | `libraries` | Library |
| `db.library_files` | `library_files` | Library |
| `db.library_folders` | `library_folders` | Library |
| `db.tags` | `tags` (edge collection) | Tagging |
| `db.tag_model_output` | `tag_model_output` (edge) | Tagging |
| `db.ml_models` | `ml_models` | ML |
| `db.ml_model_outputs` | `ml_model_outputs` | ML |
| `db.calibration_state` | `calibration_state` | ML/Calibration |
| `db.calibration_history` | `calibration_history` | ML/Calibration |
| `db.segment_scores_stats` | `segment_scores_stats` | ML |
| `db.worker_claims` | `worker_claims` | Workers |
| `db.worker_restart_policy` | `worker_restart_policy` | Workers |
| `db.health` | `health` | Infrastructure |
| `db.file_states` | `file_states` | Library |
| `db.navidrome_tracks` | `navidrome_tracks` | Navidrome |
| `db.navidrome_playcounts` | `navidrome_playcounts` | Navidrome |
| `db.sessions` | `sessions` | Infrastructure |
| `db.meta` | `meta` | Infrastructure |
| `db.vram_promises` | `vram_promises` | ML/Resources |
| `db.ml_capacity` | `ml_capacity` | ML/Resources |
| `db.vector_promotion_locks` | `vector_promotion_locks` | Vectors |
| `db.migrations` | `applied_migrations` | Platform |

Vector collections (`vectors_track_*`) are registered dynamically per backbone+library via `db.register_vectors_track_backbone()` and `db.get_vectors_track_cold()`.

---

### Helpers (`helpers/`)

**Purpose:** Pure utilities and shared data types.

**Contains:**
- `dto/` — Data transfer objects (`health_dto.py`, etc.)
- Audio file validation, file system utilities, logging setup, time helpers

**Rules:**
- **Pure functions only** (no I/O side effects beyond their stated purpose)
- **No imports from `nomarr.*`** (only stdlib and third-party)
- Stateless utilities

---

## Dependency Rules (Enforced)

### Allowed Dependencies

| Layer | Can Import |
|-------|------------|
| `interfaces` | `services`, `helpers` |
| `services` | `workflows`, `components`, `persistence`, `helpers` |
| `workflows` | `components`, `persistence` (type only), `helpers` |
| `components` | `persistence`, `helpers`, other `components` |
| `persistence` | `helpers` only |
| `helpers` | stdlib, third-party only |

### Forbidden Dependencies

| Layer | **Cannot** Import |
|-------|-------------------|
| `interfaces` | `workflows`, `components`, `persistence` |
| `services` | `interfaces` |
| `workflows` | `services`, `interfaces` |
| `components` | `workflows`, `services`, `interfaces` |
| `persistence` | `workflows`, `components`, `services`, `interfaces` |
| `helpers` | Any `nomarr.*` modules |

**Enforcement:** `import-linter` checks these rules in CI. Lateral (same-layer) imports are allowed: workflows may call other workflows, components may call other components.

---

## Data Flow: Processing a File

```
1. Worker Discovery (automatic)
   └→ services/infrastructure/workers/discovery_worker.py
      └→ queries library_files for needs_tagging=1
      └→ claims file via db.worker_claims.try_claim_file()

2. Workflow Execution
   └→ workflows/processing/process_file_wf.py
      └→ process_file_workflow(db, file_doc, config, sessions)

3. Component Logic
   ├→ components/ml/audio/ml_audio_comp.py
   │  └→ load_mono() — load audio via Essentia MonoLoader
   ├→ components/ml/audio/ml_preprocess_comp.py
   │  └→ compute_mel() — mel spectrogram via Essentia
   ├→ components/ml/inference/ml_backbone_embed_comp.py
   │  └→ embed() — ONNX backbone inference
   ├→ components/ml/inference/ml_head_pipeline_comp.py
   │  └→ run_heads() — ONNX head inference
   └→ components/tagging/tagging_writer_comp.py
      └→ write_tags() — write predictions to audio file

4. Claim Release
   └→ db.worker_claims.release_claim(file_id)
```

### Fire-and-Forget Tag Reconciliation

The write-tag endpoint uses BTS for in-process background dispatch and the pipeline endpoint for progress checks.

**Fire-and-forget dispatch:**

```text
POST /library/{id}/write-tag
    → library_if.py handler
        → TaggingService.start_write_tags_background(library_id)
            → BTS.start_task(ManagedTask(...))
                → background thread: reconcile loop until remaining == 0
    ← 202 {"status": "started", "task_id": "write_tags:{library_id}"}
```

**Status polling:**

```text
GET /library/{id}/pipeline
    → library_if.py handler
        → pipeline_service.get_pipeline_status(library_id)
            → BTS.get_task_status("write_tags:{library_id}") → state
            → DB/service aggregation → PipelineStatusResponse
    ← 200 {"library_id": "...", "state": "writing", "pending_write_count": N, "library_auto_write": true, "file_write_mode": "full", "untagged_count": null, "uncalibrated_count": null}
```

This keeps the request/response contract fast while still exposing observable progress. The POST `/library/{id}/write-tag` endpoint only starts work and returns a `task_id`; the GET `/library/{id}/pipeline` endpoint returns the full `PipelineStatusResponse`, including write progress and related pipeline state fields. `LibraryPipelineService` coordinates the worker idle-path trigger, calibration/apply callbacks, and write completion transitions behind those endpoints.

---

## Configuration Flow

### Startup Sequence

```python
# 1. Load config (services/infrastructure/config_svc.py)
config_service = ConfigService(config_path="/app/config/nomarr.yaml")
config = config_service.load_config()

# 2. Initialize database (persistence/db.py)
# Connects to ArangoDB using ARANGO_HOST env and arango_password from config
db = Database()

# 3. Prepare database — run migrations, ensure schema
# (workflows/platform/prepare_database_wf.py)
prepare_database_workflow(db=db)

# 4. Initialize ML service (services/infrastructure/ml_svc.py)
# Discovers ONNX models, builds ProcessorConfig
ml_svc = MLService(db=db, models_dir=config.models_dir)

# 5. Initialize health monitor (services/infrastructure/health_monitor_svc.py)
health_monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=db)

# 6. Initialize pipeline service (services/infrastructure/pipeline_svc.py)
pipeline_svc = LibraryPipelineService(
    db=db,
    bts=background_task_svc,
    calibration_svc=calibration_svc,
    tagging_svc=tagging_svc,
    navidrome_svc=navidrome_svc,
)

# 7. Initialize worker system (services/infrastructure/worker_system_svc.py)
worker_svc = WorkerSystemService(
    db=db,
    processor_config=ml_svc.processor_config,
    pipeline_svc=pipeline_svc,
    health_monitor=health_monitor,
)

# 8. Start workers — admission control → tier selection → spawn
worker_svc.start_all_workers()

# 9. Start API server (interfaces/api/api_app.py)
app = create_app(...)
```

**No global state** — all dependencies passed explicitly.

---

## Worker System Architecture

### Single Worker Type: Discovery Workers

Nomarr uses a single `DiscoveryWorker` type (`services/infrastructure/workers/discovery_worker.py`). Workers are identical processes that:

1. Query `library_files` for files needing processing (`needs_tagging=1`)
2. Claim files via `worker_claims` collection (atomic, deterministic `_key`)
3. Process files using `process_file_workflow`
4. Release claims after completion

There are no separate scanner or calibration workers. No queues.

### Process Model

```
Main Process (API Server)
├→ HealthMonitorService (monitoring thread)
│  └→ Polls pipes, checks deadlines, emits callbacks
│
└→ WorkerSystemService
   ├→ DiscoveryWorker 0 (separate Python process)
   │  ├→ Own Database connection
   │  ├→ Health pipe (write-end) → parent reads
   │  └→ ONNX sessions for backbone + heads
   │
   └→ DiscoveryWorker 1 (if admission control allows)
      └→ ...
```

### Health Monitoring

Worker health is tracked via **pipe/FD channels**, not database polling:
- Each worker writes health frames (`HEALTH|{json}`) to its pipe every 3 seconds
- `HealthMonitorService` reads frames and maintains an in-memory status registry
- Pipe closure = immediate crash detection
- DB writes are optional history-only snapshots

See [Health System](health.md) and [Workers & Lifecycle](workers.md) for details.

---

## File Watching Architecture

### FileWatcherService (`services/infrastructure/file_watcher_svc.py`)

Automatically detects filesystem changes and triggers incremental library scans.

**Two modes:**

| Mode | Mechanism | Best For |
|------|-----------|----------|
| Event (default) | watchdog library — real-time filesystem events | Local disks |
| Poll | Periodic full-library scans at configurable interval | Network mounts (NFS/SMB) |

**Configuration:**
```bash
export NOMARR_WATCH_MODE=poll   # or 'event' (default)
```

---

## Related Documentation

- [Domains](domains.md) — Vertical domain slices and data ownership
- [Health System](health.md) — Pipe/FD-based health monitoring
- [Workers & Lifecycle](workers.md) — DiscoveryWorker lifecycle and claim-based processing
- [Migrations](migrations.md) — Database migration system
- [Vector Stores](vector-stores.md) — Hot/cold vector architecture
- [Naming Conventions](naming.md) — File and symbol naming patterns
