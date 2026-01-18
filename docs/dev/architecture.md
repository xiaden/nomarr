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

### 2. Dependency Injection

No global state or singleton imports:

```python
# ❌ BAD - Global import
from nomarr.services import queue_service
queue_service.enqueue(...)

# ✅ GOOD - Injected dependency
def process_file(path: str, queue_service: QueueService):
    queue_service.enqueue(...)
```

### 3. Pure Workflows

Workflows orchestrate domain logic without side effects:

```python
# ✅ Workflow - Pure orchestration
def scan_library_workflow(
    library_path: str,
    db: Database,
    queue_service: QueueService
) -> ScanResult:
    files = discover_files(library_path)
    queued = queue_service.enqueue_files(files)
    return ScanResult(files_found=len(files), queued=queued)
```

### 4. Essentia Isolation

Only `ml/backend_essentia.py` imports Essentia libraries:

```python
# ❌ BAD - Direct Essentia import
import essentia_tensorflow as essentia_tf

# ✅ GOOD - Via backend module
from nomarr.ml.backend_essentia import compute_embeddings
```

---

## Layer Responsibilities

### Interfaces (`interfaces/`)

**Purpose:** Expose Nomarr to external consumers (HTTP, CLI, Web UI).

**Contains:**
- `api/` - FastAPI HTTP endpoints
- `cli/` - Command-line interface
- `web/` - Web UI routes and templates

**Rules:**
- Validate inputs
- Call exactly **one service method** per endpoint
- Serialize outputs
- **No business logic**
- **No direct database access**
- **No ML inference**

**Example:**
```python
@router.post("/process")
async def process_files(
    request: ProcessRequest,
    processing_service: ProcessingService = Depends(get_processing_service)
) -> ProcessResponse:
    # 1. Validate (handled by Pydantic)
    # 2. Call service
    result = processing_service.enqueue_files_for_tagging(request.paths)
    # 3. Serialize
    return ProcessResponse.from_dto(result)
```

---

### Services (`services/`)

**Purpose:** Own runtime resources and orchestrate workflows.

**Contains:**
- `infrastructure/` - Queue, workers, database, config
- `domain/` - Library, analytics, calibration, recalibration

**Rules:**
- Construct long-lived objects (Database, workers, ML backends)
- Inject dependencies into workflows
- Return DTOs to interfaces
- **No HTTP/CLI knowledge**
- **Orchestration only, minimal logic**

**Example:**
```python
class ProcessingService:
    def __init__(self, db: Database, ml_backend: MLBackend):
        self.db = db
        self.ml_backend = ml_backend
    
    def enqueue_files_for_tagging(self, paths: list[str]) -> EnqueueResult:
        # Orchestrate workflow with injected dependencies
        return enqueue_files_workflow(
            paths=paths,
            db=self.db,
            ml_backend=self.ml_backend
        )
```

---

### Workflows (`workflows/`)

**Purpose:** Implement core use cases and business logic.

**Contains:**
- `processing/` - File processing workflows
- `library/` - Library scanning workflows
- `calibration/` - Calibration generation workflows
- `queue/` - Queue management workflows

**Rules:**
- Accept all dependencies as parameters
- Pure functions (no hidden state)
- Call components and persistence layers
- **Never import services or interfaces**
- **No global config reads**

**Example:**
```python
def process_file_workflow(
    path: str,
    db: Database,
    ml_backend: MLBackend,
    tag_writer: TagWriter
) -> ProcessResult:
    # 1. Extract embeddings
    embeddings = ml_backend.compute_embeddings(path)
    
    # 2. Run inference
    predictions = ml_backend.predict(embeddings)
    
    # 3. Convert to tags
    tags = tag_writer.predictions_to_tags(predictions)
    
    # 4. Write tags
    tag_writer.write_tags(path, tags)
    
    # 5. Store results
    db.tags.store_predictions(path, predictions)
    
    return ProcessResult(path=path, tags_written=len(tags))
```

---

### Components (`components/`)

**Purpose:** Domain-specific heavy logic.

**Contains:**
- `analytics/` - Tag statistics, co-occurrence
- `events/` - Event broadcasting, SSE streaming
- `infrastructure/` - Path resolution
- `library/` - File tag operations, metadata extraction, search
- `metadata/` - Entity keys, seeding, caching
- `ml/` - ML inference, embeddings, calibration, Essentia backend
- `navidrome/` - Template handling
- `platform/` - ArangoDB bootstrap, GPU monitoring
- `queue/` - Queue operations, cleanup, status
- `tagging/` - Tag conversion, aggregation, reading/writing
- `workers/` - Job recovery, crash handling

**Rules:**
- Implement complex domain logic
- Can call persistence and helpers
- **No knowledge of services, workflows, or interfaces**
- **Stateless when possible**

**Example:**
```python
# components/ml/inference_comp.py
def compute_embeddings_for_backbone(
    backbone: str,
    emb_graph: str,
    path: str,
    target_sr: int,
    segment_s: float,
    hop_s: float
) -> tuple[np.ndarray, float]:
    # Heavy ML computation
    audio = load_audio(path, sr=target_sr)
    embeddings = run_model(audio, backbone, emb_graph)
    return embeddings, compute_statistics(embeddings)
```

---

### Persistence (`persistence/`)

**Purpose:** Database and queue access layer.

**Contains:**
- `db.py` - `Database` class (facade)
- `database/` - One `*Operations` class per table
  - `tag_queue_operations.py`
  - `library_operations.py`
  - `health_operations.py`
  - `analytics_operations.py`

**Rules:**
- SQL and data access **only**
- **No business logic**
- **No knowledge of workflows, services, or interfaces**
- One class per table or related table group

**Example:**
```python
# persistence/database/tag_queue_aql.py
class QueueOperations:
    def __init__(self, db: StandardDatabase):
        self.db = db
    
    def enqueue(self, path: str, force: bool = False) -> str:
        result = self.db.aql.execute(
            "INSERT { path: @path, status: 'pending', force: @force } INTO queue RETURN NEW",
            bind_vars={"path": path, "force": force}
        )
        return next(result)["_id"]
    
    def get_pending_jobs(self, limit: int = 10) -> list[Job]:
        cursor = self.db.aql.execute(
            "FOR doc IN queue FILTER doc.status == 'pending' LIMIT @limit RETURN doc",
            bind_vars={"limit": limit}
        )
        return [Job.from_doc(doc) for doc in cursor]
```
```

**Access Pattern:**
```python
# ✅ GOOD - Via Database facade
db = Database()  # Connects using ARANGO_HOST env and config
job_id = db.tag_queue.enqueue("/music/track.mp3")

# ❌ BAD - Direct import
from nomarr.persistence.database.tag_queue_operations import TagQueueOperations
```

---

### Helpers (`helpers/`)

**Purpose:** Pure utilities and shared data types.

**Contains:**
- `audio.py` - Audio file validation and metadata
- `files.py` - File system utilities
- `dataclasses.py` - Shared dataclasses (configs, DTOs)
- `logging.py` - Logging setup
- `dto/` - Data transfer objects

**Rules:**
- **Pure functions only** (no I/O, no side effects)
- **No imports from `nomarr.*`** (only stdlib and third-party)
- Stateless utilities

**Example:**
```python
# helpers/audio.py
def validate_audio_file(path: str) -> bool:
    """Check if file is supported audio format."""
    return path.lower().endswith(('.mp3', '.m4a', '.flac', '.ogg', '.opus'))

def get_audio_duration(path: str) -> float:
    """Get audio duration in seconds."""
    audio = mutagen.File(path)
    return audio.info.length if audio else 0.0
```

---

## Dependency Rules (Enforced)

### Allowed Dependencies

| Layer | Can Import |
|-------|------------|
| `interfaces` | `services`, `helpers` |
| `services` | `workflows`, `components`, `persistence`, `helpers` |
| `workflows` | `components`, `persistence`, `helpers` |
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

**Enforcement:** `import-linter` checks these rules in CI.

---

## Data Flow Example

### Processing a File

```
1. HTTP Request
   └─> interfaces/api/web/processing_if.py
       └─> process_files(request)

2. Service Orchestration
   └─> services/domain/processing_svc.py
       └─> enqueue_files_for_tagging(paths)

3. Workflow Execution
   └─> workflows/processing/enqueue_wf.py
       └─> enqueue_files_workflow(paths, db, queue_service)

4. Component Logic
   ├─> components/queue/enqueue_comp.py
   │   └─> enqueue_file(db, path)
   │
   └─> persistence/database/tag_queue_operations.py
       └─> SQL INSERT INTO tag_queue

5. Worker Processing
   └─> components/workers/tag_worker.py
       ├─> components/ml/inference_comp.py
       │   └─> compute_embeddings(...)
       │
       ├─> components/tagging/convert_comp.py
       │   └─> predictions_to_tags(...)
       │
       └─> components/tagging/write_comp.py
           └─> write_tags_to_file(...)

6. State Broadcasting
   └─> components/events/event_broker_comp.py
       └─> StateBroker polls DB → broadcasts SSE
```

---

## Configuration Flow

### Startup Sequence

```python
# 1. Load config (services/infrastructure/config_svc.py)
config_service = ConfigService(config_path="/app/config/config.yaml")
config = config_service.load_config()

# 2. Initialize database (persistence/db.py)
# Database connects to ArangoDB using ARANGO_HOST env and arango_password from config
db = Database()

# 3. Initialize ML backend (components/ml/backend_essentia.py)
ml_backend = EssentiaBackend(models_dir=config.models_dir)

# 4. Initialize services (services/domain/*.py)
processing_service = ProcessingService(db=db, ml_backend=ml_backend)
queue_service = QueueService(db=db, queue_type="tag")
worker_service = WorkerSystemService(db=db, config=config)

# 5. Start workers (services/infrastructure/worker_system_svc.py)
worker_service.start_all_workers()

# 6. Start API server (interfaces/api/app.py)
app = create_app(
    processing_service=processing_service,
    queue_service=queue_service,
    worker_service=worker_service
)
```

**No global state** - all dependencies passed explicitly.

---

## DTO Flow

### Request → DTO → Response

```
1. HTTP Request (JSON)
   └─> Pydantic Model (interfaces/api/types/*.py)

2. Convert to DTO
   └─> helpers/dto/*.py (ProcessRequest → ProcessFileDTO)

3. Pass to Service
   └─> service method receives DTO

4. Service returns DTO
   └─> helpers/dto/*.py (ProcessFileResult)

5. Convert to Response
   └─> Pydantic Model (interfaces/api/types/*.py)

6. HTTP Response (JSON)
```

**Example:**
```python
# 1. Request Model (interfaces/api/types/processing_types.py)
class ProcessRequest(BaseModel):
    paths: list[str]
    force: bool = False

# 2. DTO (helpers/dto/processing_dto.py)
@dataclass
class ProcessFileDTO:
    paths: list[str]
    force: bool

# 3. Service
def enqueue_files_for_tagging(self, request: ProcessFileDTO) -> EnqueueResult:
    ...

# 4. Result DTO (helpers/dto/queue_dto.py)
@dataclass
class EnqueueResult:
    job_ids: list[int]
    files_queued: int

# 5. Response Model (interfaces/api/types/processing_types.py)
class ProcessResponse(BaseModel):
    job_ids: list[int]
    files_queued: int
    
    @classmethod
    def from_dto(cls, dto: EnqueueResult) -> ProcessResponse:
        return cls(job_ids=dto.job_ids, files_queued=dto.files_queued)
```

---

## Worker System Architecture

### Process Model

```
Main Process (API Server)
├─> WorkerSystemService
    ├─> Worker Process (Tag)
    │   ├─> Own Database Connection
    │   ├─> Heartbeat Writer
    │   └─> Job Processor
    │
    ├─> Worker Process (Library)
    │   ├─> Own Database Connection
    │   ├─> Heartbeat Writer
    │   └─> Library Scanner
    │
    └─> Worker Process (Calibration)
        ├─> Own Database Connection
        ├─> Heartbeat Writer
        └─> Recalibration Processor
```

**Key Points:**
- Separate Python processes (`multiprocessing.Process`)
- Each worker has **own database connection** (for process isolation)
- Workers communicate via **database collections** (health, queue)
- StateBroker polls database and broadcasts to SSE clients

See [Workers & Lifecycle](workers.md) for details.

---

## File Watching Architecture

### FileWatcherService (Infrastructure Service)

**Purpose:** Automatically detect filesystem changes and trigger incremental library scans.

**Location:** `services/infrastructure/file_watcher_svc.py`

**Dependencies:**
- `watchdog` library (cross-platform file system events - event mode only)
- `Database` (for library metadata)
- `LibraryService` (for triggering scans)
- asyncio event loop (for debouncing and polling)

### Watch Modes

FileWatcherService supports two modes for detecting filesystem changes:

**Event Mode (Default):**
- Uses watchdog library for real-time filesystem events
- Fast response time (2-5 seconds from file change to scan trigger)
- Low overhead (< 0.1% CPU idle, ~1-2 MB RAM per library)
- **Limitation:** May not reliably detect changes on network mounts (NFS/SMB/CIFS)
- Best for: Local filesystems (ext4, NTFS, APFS)

**Polling Mode (Network-Mount-Safe):**
- Periodic full-library scans at configurable intervals
- Default interval: 60 seconds (configurable via `polling_interval_seconds`)
- Slower response time but guaranteed detection
- Slightly higher overhead during scan periods
- Best for: Network mounts, remote shares, virtualized filesystems

**Configuration:**
```bash
# Environment variable (applies globally)
export NOMARR_WATCH_MODE=poll  # or 'event' (default)

# Or via FileWatcherService constructor
watcher = FileWatcherService(
    db=db,
    library_service=library_service,
    watch_mode="poll",           # 'event' or 'poll'
    polling_interval_seconds=90  # Only used in poll mode
)
```

**Mode Selection Guidelines:**
- Local filesystem (local disk, SSD): Use `event` mode (default)
- Network mount (NFS, SMB, CIFS): Use `poll` mode
- Docker bind mount from host: Use `event` mode (usually reliable)
- Virtualized filesystem: Test with `event` first, fallback to `poll` if unreliable

### Threading Model (Event Mode)

```
Main Thread (Asyncio Event Loop)
    └─> FileWatcherService
        ├─> Observer Thread 1 (Library A)
        │   └─> LibraryEventHandler
        │       └─> on_any_event() [Background Thread]
        │           └─> loop.call_soon_threadsafe() → asyncio task
        │
        ├─> Observer Thread 2 (Library B)
        │   └─> LibraryEventHandler
        │       └─> on_any_event() [Background Thread]
        │           └─> loop.call_soon_threadsafe() → asyncio task
        │
        └─> Debounce Task (Asyncio)
            └─> await asyncio.sleep(debounce_seconds)
            └─> LibraryService.scan_targets()
```

**Critical Threading Rules (Event Mode):**
1. Watchdog callbacks run on **background threads** (NOT asyncio event loop)
2. NEVER call `asyncio.create_task()` directly from watchdog callbacks
3. Use `loop.call_soon_threadsafe()` to schedule asyncio tasks from threads
4. All async operations must go through event loop handoff

### Polling Model (Poll Mode)

```
Main Thread (Asyncio Event Loop)
    └─> FileWatcherService
        ├─> Polling Task 1 (Library A) [Asyncio]
        │   └─> while True:
        │       └─> await asyncio.sleep(polling_interval)
        │       └─> LibraryService.scan_targets([full_library])
        │
        └─> Polling Task 2 (Library B) [Asyncio]
            └─> while True:
                └─> await asyncio.sleep(polling_interval)
                └─> LibraryService.scan_targets([full_library])
```

**Polling Mode Characteristics:**
- Pure asyncio (no background threads or multiprocessing)
- One asyncio.Task per library
- Each task sleeps for polling_interval, then triggers full-library scan
- Minimal state: only last_poll_time dict
- Errors in scan do not stop polling loop

### Event Flow

```
1. File System Change
   └─> watchdog detects event (inotify/FSEvents/ReadDirectoryChangesW)

2. LibraryEventHandler.on_any_event() [Background Thread]
   ├─> Filter: audio/playlist/image files only
   ├─> Ignore: temp files, hidden files, directories
   └─> Convert: absolute path → library-relative path

3. FileWatcherService._on_file_change() [Thread-Safe]
   ├─> Lock pending_changes set
   ├─> Add (library_id, relative_path)
   └─> Schedule debounce task via loop.call_soon_threadsafe()

4. Debounce Task [Asyncio]
   ├─> await asyncio.sleep(debounce_seconds)
   ├─> Collect pending changes
   ├─> Map files → parent folders (ScanTargets)
   ├─> Deduplicate (Rock subsumes Rock/Beatles)
   └─> LibraryService.scan_targets()

5. Incremental Scan [Asyncio]
   └─> scan_library_direct_workflow(targets=[...])
```

### Debouncing Strategy

**Problem:** User copies 100 files → 100 filesystem events → 100 scans

**Solution:** Batch all events within a quiet period

```python
# Default: 2.0 seconds
debounce_seconds = 2.0

# Event timeline:
T+0.0s: file1.mp3 modified → timer starts
T+0.5s: file2.mp3 added → timer resets
T+1.2s: file3.mp3 deleted → timer resets
T+3.2s: no more events → scan triggers (after 2s quiet)
```

**Benefits:**
- 100 events → 1 scan (100x reduction)
- Waits for bulk operations to complete
- Configurable per deployment (TODO: add to config.yaml)

### Target Deduplication

**Problem:** Multiple files in same folder → redundant scan targets

**Solution:** Deduplicate parent-child relationships

```python
# Input: File changes
changes = [
    ("Rock/Beatles/Abbey Road/track1.mp3", modified),
    ("Rock/Beatles/Abbey Road/track2.mp3", added),
    ("Rock/Beatles/Let It Be/track3.mp3", modified),
    ("Jazz/Miles Davis/Kind of Blue/track4.mp3", added)
]

# Step 1: Map files → parent folders
targets = [
    ScanTarget(library_id=1, folder_path="Rock/Beatles/Abbey Road"),
    ScanTarget(library_id=1, folder_path="Rock/Beatles/Let It Be"),
    ScanTarget(library_id=1, folder_path="Jazz/Miles Davis/Kind of Blue")
]

# Step 2: Deduplicate (if user adds "Rock" later)
# "Rock" subsumes "Rock/Beatles/*"
deduplicated = [
    ScanTarget(library_id=1, folder_path="Rock"),
    ScanTarget(library_id=1, folder_path="Jazz/Miles Davis/Kind of Blue")
]
```

**Deduplication Rules:**
1. Parent folder subsumes all child folders
2. Empty `folder_path` ("") = full library scan → subsumes all
3. Sibling folders kept separate (Rock vs Jazz)

### Lifecycle Integration

**Startup (app.py Application.start()):**
```python
# 1. Register FileWatcherService after LibraryService
file_watcher = FileWatcherService(
    db=self.database,
    library_service=self.library_service,
    debounce_seconds=2.0,
    event_loop=asyncio.get_event_loop()
)
self.register_service("file_watcher", file_watcher)

# 2. Auto-start watchers for all enabled libraries
libraries = self.database.library.get_all(enabled_only=True)
for library in libraries:
    try:
        file_watcher.start_watching_library(library["_key"])
        logger.info(f"Started file watcher for library: {library['name']}")
    except Exception as e:
        logger.warning(f"Failed to start watcher for {library['name']}: {e}")
```

**Shutdown (app.py Application.stop()):**
```python
# Stop watchers BEFORE stopping other services
if self.file_watcher:
    logger.info("Stopping file watchers")
    self.file_watcher.stop_all()  # Joins all observer threads

# Then stop workers, event broker, health monitor, etc.
```

### Configuration (TODO: Add to config.yaml)

```yaml
file_watching:
  mode: "event"              # 'event' (default) or 'poll'
  enabled: true              # Enable/disable file watching globally
  debounce_seconds: 2.0      # Quiet period before triggering scan (event mode)
  polling_interval: 60       # Seconds between scans (poll mode)
  batch_size: 200            # Files per batch write in incremental scans
  
libraries:
  - name: "Music"
    path: "/music"
    enabled: true
    watch_enabled: true      # Per-library enable/disable (TODO)
```

**Current Implementation:**
- `watch_mode` via `NOMARR_WATCH_MODE` environment variable or constructor parameter
- `polling_interval_seconds` via constructor parameter only (default: 60s)
- Other options are TODOs for future implementation

### Performance Characteristics

**Memory Usage:**
- ~1-2 MB per library (watchdog overhead)
- Pending changes: O(changed files) until debounce fires
- Typically < 5 MB total for 5 libraries

**CPU Usage:**
- Idle: <0.1% (OS handles inotify/FSEvents)
- Active: <1% (event filtering + debouncing)
- Scan: Same as manual scan (dependent on file count)

**Responsiveness:**
- Detection latency: <1 second (OS filesystem notification)
- Debounce delay: 2 seconds (configurable)
- Total: ~3-5 seconds from file save to scan start

**Scan Speedup ( (Event Mode):**
- watchdog may not receive events on NFS/SMB/CIFS mounts
- Depends on OS-level filesystem event support
- Mitigation: Use `NOMARR_WATCH_MODE=poll` environment variable
- Fallback: Manual scan button always available

**Network Mounts (Poll Mode):**
- Reliable detection via periodic scans
- Higher latency (default 60 seconds vs 2-5 seconds for event mode)
- Slightly higher CPU usage during scan intervals
- No threading complexity (pure asyncio)

**Bulk Operations:**
- Event mode: Debouncing batches rapid changes (2s quiet period)
- Poll mode: Full scan happens regardless of change volume
- Both modes: May take time to process all targets after detection

**Concurrent Scans:**
- Service checks `last_scan_started_at` to detect in-progress scans
- Raises `RuntimeError` if scan already running
- Future: Queue targets for next scan instead of failing

**Symlink Handling:**
- Event mode: watchdog follows symlinks by default
- May cause duplicate events if symlink points inside watched tree
- TODO: Test and document symlink behavior

**Polling Mode Overhead:**
- Each library scans entire root every polling_interval
- For large libraries (10k+ files): each poll takes 1-5 seconds
- Recommended minimum interval: 30 seconds
- Recommended maximum interval: 120 seconds for reasonable responsiveness detect in-progress scans
- Raises `RuntimeError` if scan already running
- Future: Queue targets for next scan instead of failing

**Symlink Handling:**
- watchdog follows symlinks by default
- May cause duplicate events if symlink points inside watched tree
- TODO: Test and document symlink behavior

### API Methods

**FileWatcherService:**
```python
def start_watching_library(self, library_id: str) -> None:
    """Start watching filesystem for library. Raises ValueError if library not found."""

def stop_watching_library(self, library_id: str) -> None:
    """Stop watching specific library. Safe to call if not watching."""

def stop_all(self) -> None:
    """Stop all watchers. Called during shutdown."""

def _on_file_change(self, library_id: str, relative_path: str) -> None:
    """Thread-safe event handler. Called from watchdog threads."""

def _schedule_debounce(self, library_id: str) -> None:
    """Schedule debounce task via asyncio event loop."""

async def _trigger_after_debounce(self, library_id: str) -> None:
    """Wait for quiet period, then trigger scan."""

def _paths_to_scan_targets(self, library_id: str, paths: set[str]) -> list[ScanTarget]:
    """Map changed files to parent folder targets."""

def _deduplicate_targets(self, targets: list[ScanTarget]) -> list[ScanTarget]:
    """Remove child folders when parent present."""
```

### Testing Strategy

**Unit Tests (tests/unit/services/test_file_watcher_svc.py):**
- Event filtering (audio only, ignore temp/hidden)
- Debouncing (multiple events → one scan)
- Target mapping (files → parent folders)
- Deduplication (parent subsumes children)
- Thread safety (concurrent events)
- Lifecycle (start/stop watchers)

**Integration Tests (Deferred):**
- Real filesystem events → scan workflow
- Interrupted scan detection
- Batch writes verification
- Cross-platform compatibility (Windows/Linux/macOS)

See [REFACTOR_PLAN_INCREMENTAL_SCAN.md](REFACTOR_PLAN_INCREMENTAL_SCAN.md) for full details.

---

## Testing Strategy

### Unit Tests

Test components and workflows in isolation:

```python
# tests/unit/components/test_ml_inference.py
def test_compute_embeddings():
    # Mock dependencies
    mock_backend = MockMLBackend()
    
    # Call component
    embeddings = compute_embeddings_for_backbone(
        backbone="effnet",
        emb_graph="test.pb",
        path="test.mp3",
        target_sr=16000,
        segment_s=1.0,
        hop_s=0.5
    )
    
    assert embeddings.shape == (10, 256)
```

### Integration Tests

Test workflows with real database:

```python
# tests/integration/test_processing_workflow.py
def test_process_file_workflow(tmp_db):
    db = Database(tmp_db)
    ml_backend = MockMLBackend()
    
    result = process_file_workflow(
        path="/test/track.mp3",
        db=db,
        ml_backend=ml_backend,
        tag_writer=MockTagWriter()
    )
    
    assert result.tags_written > 0
    assert db.tags.get_track_tags("/test/track.mp3") is not None
```

### Service Tests

Test service orchestration:

```python
# tests/unit/services/test_processing_service.py
def test_enqueue_files_for_tagging():
    mock_db = MockDatabase()
    mock_ml = MockMLBackend()
    
    service = ProcessingService(db=mock_db, ml_backend=mock_ml)
    result = service.enqueue_files_for_tagging(["/test/track.mp3"])
    
    assert result.files_queued == 1
    assert len(result.job_ids) == 1
```

---

## Error Handling

### Layer-Specific Strategies

**Interfaces:**
- Catch exceptions from services
- Convert to HTTP error responses
- Log errors with context

**Services:**
- Let exceptions bubble to interfaces
- Wrap only for context enhancement
- Return error DTOs when appropriate

**Workflows:**
- Raise domain-specific exceptions
- Let callers handle recovery
- Log critical errors only

**Components:**
- Raise on invalid inputs
- Document expected exceptions
- No silent failures

**Example:**
```python
# Component
def compute_embeddings(path: str) -> np.ndarray:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Audio file not found: {path}")
    # ...

# Workflow
def process_file_workflow(path: str, ...) -> ProcessResult:
    try:
        embeddings = compute_embeddings(path)
    except FileNotFoundError as e:
        raise ProcessingError(f"Cannot process file: {e}")
    # ...

# Service
def enqueue_file(self, path: str) -> EnqueueResult:
    # Let exceptions bubble
    return enqueue_file_workflow(path, db=self.db, ...)

# Interface
@router.post("/process")
async def process_file(request: ProcessRequest, ...):
    try:
        result = processing_service.enqueue_file(request.path)
        return ProcessResponse.from_dto(result)
    except ProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception("Unexpected error processing file")
        raise HTTPException(status_code=500, detail="Internal server error")
```

---

## Performance Considerations

### Database Connections

- **One connection per worker process**
- ArangoDB handles concurrent access natively
- Connection pooling managed by python-arango client

### ML Model Caching

- Models loaded once per worker
- Cached in GPU VRAM (effnet: 9GB)
- Persists across jobs (no reload overhead)

### Queue Processing

- Workers poll every 2 seconds
- Batch processing not implemented (single-file jobs)
- Parallel processing via multiple workers

### SSE Broadcasting

- StateBroker polls DB every 1-2 seconds
- Minimal CPU overhead (<1%)
- ~100 concurrent SSE clients supported

---

## Related Documentation

- [Services Layer](services.md) - Service responsibilities and APIs
- [Workers & Lifecycle](workers.md) - Worker process model
- [StateBroker & SSE](statebroker.md) - Real-time state broadcasting
- [Queue System](queues.md) - Queue processing and DTOs
- [Naming Standards](naming.md) - Code naming conventions
