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
- `ml/` - ML inference, embeddings, calibration
- `tagging/` - Tag conversion, aggregation, writing
- `analytics/` - Tag statistics, correlations
- `queue/` - Queue operations and status
- `events/` - Event broadcasting (StateBroker)

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
db = Database(db_path)
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
