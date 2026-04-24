# ML Pipeline Automation — Contracts Ledger

**Design Document:** [DD-ml-pipeline-automation](../../pending/DD-ml-pipeline-automation.md)
**Feature Slug:** ml-pipeline-automation

---

## Architectural Rules

- Library pipeline state graph follows `file_has_state` pattern (ADR-003): singleton vertices, atomic REMOVE+INSERT transitions
- Schema additions follow ADR-004 graph normalization: proper edge collections, graph definitions
- Tag writeback follows two-phase model (ADR-008): DB curation first, file writeback second
- All background operations use ManagedTask + BackgroundTaskService (BTS)
- No retry/backoff/ERROR_WAIT — failures error loudly, startup recovery corrects stale states
- Migration AQL must separate reads and writes (ArangoDB ERR 1579 prevention)

---

## Collections & State Constants

### Vertex Collection: `library_pipeline_states` (10 singletons)

```
idle, scanning, ml_running, too_small, awaiting_calibration,
calibrating, applying, write_ready, writing, done
```

### Edge Collection: `library_has_pipeline_state`

- `_from`: `libraries/{key}` → `_to`: `library_pipeline_states/{state}`
- One edge per library (single-axis, not boolean pairs)

### State Constants (`nomarr/persistence/database/library_pipeline_states_aql.py`)

```python
PIPELINE_IDLE = "library_pipeline_states/idle"
PIPELINE_SCANNING = "library_pipeline_states/scanning"
PIPELINE_ML_RUNNING = "library_pipeline_states/ml_running"
PIPELINE_TOO_SMALL = "library_pipeline_states/too_small"
PIPELINE_AWAITING_CALIBRATION = "library_pipeline_states/awaiting_calibration"
PIPELINE_CALIBRATING = "library_pipeline_states/calibrating"
PIPELINE_APPLYING = "library_pipeline_states/applying"
PIPELINE_WRITE_READY = "library_pipeline_states/write_ready"
PIPELINE_WRITING = "library_pipeline_states/writing"
PIPELINE_DONE = "library_pipeline_states/done"
```

### Graph: `pipeline_graph`

- Edge definition: `library_has_pipeline_state` from `libraries` to `library_pipeline_states`

### Library Document Field

- `library_auto_write: bool` (default `false`) — added by V023 migration

## Persistence Methods

### LibraryPipelineStatesOps (`nomarr/persistence/database/library_pipeline_states_aql.py`)

```python
class LibraryPipelineStatesOps:
    def __init__(self, db: DatabaseLike) -> None: ...
    def transition_state(self, library_id: str, to_state: str) -> None: ...  # Atomic REMOVE+INSERT. No-op if already at target.
    def get_state(self, library_id: str) -> str: ...  # Returns state key e.g. 'idle'. Raises ValueError if no edge.
    def get_libraries_in_state(self, state: str) -> list[str]: ...  # INBOUND traversal, returns library _id list
    def bulk_transition(self, from_state: str, to_state: str) -> int: ...  # Returns count transitioned
    def find_ml_complete_libraries(self, min_files: int) -> list[dict]: ...  # AQL: ml_running libs with 0 untagged files. Returns [{library_id, tagged_count}]
```

### Database Wiring (`nomarr/persistence/db.py`)

- `Database.library_pipeline_states: LibraryPipelineStatesOps`

## Service Methods

### LibraryPipelineService (`nomarr/services/infrastructure/pipeline_svc.py`)

```python
class LibraryPipelineService:
    def __init__(self, db: Database, bts: BackgroundTaskService, calibration_svc: CalibrationService, tagging_svc: TaggingService, navidrome_svc: NavidromeService) -> None: ...
    def recover_stale_states(self) -> dict[str, int]: ...  # scanning→idle, calibrating→awaiting_calibration, applying→awaiting_calibration, writing→write_ready
    def trigger_calibration(self) -> None: ...  # PUBLIC — called by worker idle-path (Plan D). Bulk awaiting_calibration → calibrating, dispatch calibration or shortcut to applying
    def on_calibration_complete(self) -> None: ...  # Post-generation hook target. calibrating → applying, dispatch apply
    def on_apply_complete(self) -> None: ...  # Per-library branching: applying → writing (auto_write + write_mode) or applying → write_ready
    def on_write_complete(self, library_id: str) -> None: ...  # writing → done + Navidrome rescan
    def _dispatch_apply(self) -> None: ...  # BTS dispatch of calibration apply with on_complete=on_apply_complete
    def _dispatch_write(self, library_id: str) -> None: ...  # BTS dispatch of write_tags_background with on_complete=on_write_complete
```

### Hook Wiring Changes (Plan C)

```python
# OLD (app.py):
calibration_service.set_post_generation_hook(tagging_service.start_apply_calibration_background)

# NEW (app.py):
calibration_service.set_post_generation_hook(pipeline_svc.on_calibration_complete)
```

*(Additional service methods populated after Plan E)*

### TaggingService Renames (Plan E)

```python
# nomarr/services/domain/tagging_svc.py
class TaggingService:
    def write_tags_to_files(self, library_id: str, batch_size: int = 100, namespace: str = "nom") -> WriteTagsResult: ...  # RENAMED from reconcile_library
    # start_write_tags_background — unchanged, internally calls write_tags_to_files
    # get_reconcile_status — unchanged (internal-only, route deleted)
    # commit_pending_tags — internally calls write_tags_to_files
```

## API Contracts

### Renamed Route (Plan E)

- `POST /api/web/library/{library_id}/write-tag` → 202, `StartTagWriteResponse` — renamed from `/reconcile-tags`

### Deleted Routes (Plan E)

- ~~`GET /api/web/library/{library_id}/reconcile-status`~~ — deleted, replaced by pipeline endpoint

### New Route (Plan E)

- `GET /api/web/library/{library_id}/pipeline` → 200, `PipelineStatusResponse` — returns pipeline state + selective counts. 404 if library not found.

### Reactive Toggle (Plan E)

- `PATCH /api/web/library/{library_id}` — when `library_auto_write` changes:
  - `false → true` + state `write_ready`: dispatch `_dispatch_write(library_id)` → `writing`
  - `true → false` + state `writing`: set stop_event on BTS task → transitions `writing → write_ready` at next checkpoint

## DTOs

### LibraryDict (Plan B)

- `library_auto_write: bool = False` — added to `nomarr/helpers/dto/library_dto.py`

### WriteTagsResult (Plan E)

```python
# nomarr/helpers/dto/library_dto.py — RENAMED from ReconcileTagsResult
@dataclass
class WriteTagsResult:
    processed: int
    remaining: int
    failed: int
```

### LibraryPipelineStatusDTO (Plan E)

```python
# nomarr/helpers/dto/library_dto.py
@dataclass
class LibraryPipelineStatusDTO:
    library_id: str
    state: str  # PipelineState literal
    untagged_count: int | None
    uncalibrated_count: int | None
    pending_write_count: int | None
    library_auto_write: bool
    file_write_mode: str
```

### API Request/Response Types (Plan B)

- `CreateLibraryRequest.library_auto_write: bool = False`
- `UpdateLibraryRequest.library_auto_write: bool | None = None`
- `LibraryResponse.library_auto_write: bool = False`

### API Response Types (Plan E)

```python
# nomarr/interfaces/api/types/library_types.py
class WriteTagsResponse(BaseModel):  # RENAMED from ReconcileTagsResponse
    processed: int
    remaining: int
    failed: int
    @classmethod
    def from_dto(cls, result: WriteTagsResult) -> WriteTagsResponse: ...

class PipelineStatusResponse(BaseModel):  # NEW
    library_id: str
    state: Literal["idle", "scanning", "ml_running", "too_small", "awaiting_calibration", "calibrating", "applying", "write_ready", "writing", "done"]
    untagged_count: int | None
    uncalibrated_count: int | None
    pending_write_count: int | None
    library_auto_write: bool
    file_write_mode: str
    @classmethod
    def from_dto(cls, dto: LibraryPipelineStatusDTO) -> PipelineStatusResponse: ...
```

### Deleted Types (Plan E)

- ~~`ReconcileTagsResult`~~ → renamed to `WriteTagsResult`
- ~~`ReconcileStatusResult`~~ → deleted (unused in Python)
- ~~`ReconcileTagsResponse`~~ → renamed to `WriteTagsResponse`
- ~~`ReconcileStatusResponse`~~ → deleted (replaced by `PipelineStatusResponse`)

## Hook Wiring

### Health Pipe Protocol Extension (Plan D)

```python
# nomarr/helpers/dto/health_dto.py
PIPELINE_FRAME_PREFIX = "PIPELINE|"  # New prefix alongside HEALTH_FRAME_PREFIX

# nomarr/services/infrastructure/health_monitor_svc.py
class HealthMonitorService:
    def set_pipeline_callback(self, callback: Callable[[], None] | None) -> None: ...
    # _handle_frame extended: forwards PIPELINE| frames to registered callback
```

## Constants Cleanup (Plan G)

### Deleted Constants (`nomarr/services/infrastructure/config_svc.py`)

```python
# DELETED — replaced by event-driven pipeline
INTERNAL_CALIBRATION_AUTO_RUN = False
INTERNAL_CALIBRATION_CHECK_INTERVAL = 604800
```

### Deleted Re-exports

- `nomarr/services/infrastructure/__init__.py` — remove import + `__all__` entry for both
- `nomarr/services/__init__.py` — remove import + `__all__` entry for both

### Kept Constants

- `INTERNAL_CALIBRATION_MIN_FILES` — still used by idle-path `too_small` gate (Plan D)

### Worker → Main Process Calibration Trigger (Plan D)

```python
# DiscoveryWorker.run() idle path sends:
self._health_pipe.send(PIPELINE_FRAME_PREFIX + "calibration_trigger")

# WorkerSystemService receives via pipeline callback → calls pipeline_svc.trigger_calibration()
```

## Dashboard / Work-Status Pipeline Extension (Plan F)

### DTOs

```python
# nomarr/helpers/dto/info_dto.py
@dataclass
class LibraryPipelineInfo:
    library_id: str
    name: str
    state: str  # Pipeline state key (idle, scanning, ml_running, etc.)
    library_auto_write: bool

# Extended field on WorkStatusResult:
class WorkStatusResult:
    # ... existing fields ...
    pipeline_libraries: list[LibraryPipelineInfo]  # NEW — per-library pipeline state
```

### API Response Types

```python
# nomarr/interfaces/api/types/info_types.py
class LibraryPipelineInfoResponse(BaseModel):
    library_id: str
    name: str
    state: str
    library_auto_write: bool
    @classmethod
    def from_dto(cls, dto: LibraryPipelineInfo) -> LibraryPipelineInfoResponse: ...

# Extended field on WorkStatusResponse:
class WorkStatusResponse(BaseModel):
    # ... existing fields ...
    pipeline_libraries: list[LibraryPipelineInfoResponse]  # NEW
```

### Component

```python
# nomarr/components/library/work_status_comp.py
def compute_work_status(
    libraries: list[dict[str, Any]],
    stats: LibraryStatsResult,
    recently_tagged_count: int,
    pipeline_states: dict[str, str],  # NEW — library_id → state key
    velocity_window_seconds: int = 300,
) -> WorkStatusResult: ...
```

### Service

```python
# nomarr/services/domain/library_svc/query.py
def get_work_status(self) -> WorkStatusResult:
    # Extended: bulk-fetches pipeline states via db.library_pipeline_states
    # and passes dict[library_id, state] to compute_work_status()
```

### Frontend Interfaces (Plan F)

```typescript
// frontend/src/shared/api/processing.ts
interface PipelineLibrary {
  library_id: string;
  name: string;
  state: string;
  library_auto_write: boolean;
}

// Extended on WorkStatus:
interface WorkStatus {
  // ... existing fields ...
  pipeline_libraries: PipelineLibrary[];  // NEW
}

// frontend/src/shared/api/library.ts — RENAMES
// reconcileTags(libraryId) → writeTags(libraryId)  route: POST /write-tag
// getReconcileStatus(libraryId) → getPipelineStatus(libraryId)  route: GET /pipeline
// Library interface gains: library_auto_write: boolean
// CreateLibraryPayload gains: library_auto_write?: boolean
// UpdateLibraryPayload gains: library_auto_write?: boolean
```

### Scan Lifecycle → Pipeline State (Plan B)

```python
# scan_setup_wf.py — unconditional on scan start
db.library_pipeline_states.transition_state(library_id, PIPELINE_SCANNING)

# scan_lifecycle_comp.py — on scan completion callback
def on_scan_complete_pipeline_hook(db: Database, library_id: str) -> None:
    file_count = db.library_files.count_library_files(library_id)
    if file_count > 0:
        db.library_pipeline_states.transition_state(library_id, PIPELINE_ML_RUNNING)
    else:
        db.library_pipeline_states.transition_state(library_id, PIPELINE_IDLE)

# scan.py — ManagedTask dispatch
ManagedTask(
    task_id=task_id,
    fn=...,
    on_complete=functools.partial(on_scan_complete_pipeline_hook, self.db, library_id),
    daemon=True,
)
```

### Library Creation → Initial Idle Edge (Plan B)

```python
# library_admin_comp.py — after db.libraries.create_library()
db.library_pipeline_states.transition_state(library_id, PIPELINE_IDLE)
```

*(Calibration hooks documented above in Service Methods — see LibraryPipelineService and Hook Wiring Changes)*

## Decisions

- **Plan D: Cross-process calibration trigger** — Worker subprocess cannot call `LibraryPipelineService` directly (BTS, CalibrationService are main-process). Solution: extend health pipe protocol with `PIPELINE_FRAME_PREFIX`, forward through `HealthMonitorService` to `WorkerSystemService` callback. See exec-planner log L16.

*(Accumulated during planning)*

---

## Existing APIs (Verified)

### BackgroundTaskService (`nomarr/services/infrastructure/background_tasks_svc.py`)

- `start_task(task: ManagedTask) -> str` — raises ValueError on duplicate task_id
- `cancel_task(task_id: str) -> bool`
- `get_task_status(task_id: str) -> dict[str, Any] | None`

### ManagedTask (`nomarr/helpers/managed_task.py`)

- `task_id: str`, `fn: Callable[[], Any]`, `stop_event: threading.Event`, `on_complete: Callable[[], None] | None`, `daemon: bool`

### CalibrationService (`nomarr/services/domain/calibration_svc.py`)

- `start_histogram_calibration_background() -> None` — guards against double-start
- `is_generation_running() -> bool`
- `set_post_generation_hook(hook: Callable[[], None]) -> None` — wraps with heads_failed==0 guard
- `CALIBRATION_GENERATE_TASK_ID` — module constant

### CalibrationStateOperations (`nomarr/persistence/database/calibration_state_aql.py`)

- `get_all_calibration_states() -> list[dict[str, Any]]` — DB-backed calibration existence check

### TaggingService (`nomarr/services/domain/tagging_svc.py`)

- `write_tags_to_files(library_id, batch_size=100, namespace="nom") -> WriteTagsResult` — RENAMED from `reconcile_library` (Plan E)
- `start_write_tags_background(library_id, stop_event, on_complete=None) -> str` — task_id = `f"write_tags:{library_id}"`
- `start_apply_calibration_background()` — exists, used as post-gen hook target

### FileStatesOperations (`nomarr/persistence/database/file_states_aql.py`)

- State constants: `"file_states/{label}"` pattern
- `_transition_state(file_id, axis, to_positive) -> None` — atomic REMOVE+INSERT
- `count_untagged_files(library_id) -> int`
- `count_uncalibrated_files(library_id) -> int`

### Database class (`nomarr/persistence/db.py`)

- Operations wired as attributes: `self.file_states = FileStatesOperations(self.db)`
- Pattern: import class, assign in `__init__`

### ConfigService constants (`nomarr/services/infrastructure/config_svc.py`)

- `INTERNAL_CALIBRATION_AUTO_RUN = False` — TO BE DELETED
- `INTERNAL_CALIBRATION_CHECK_INTERVAL = 604800` — TO BE DELETED
- `INTERNAL_CALIBRATION_MIN_FILES = 100` — KEPT

### Scan lifecycle

- `scan_setup_workflow(db, library_id, scan_type) -> dict` — validates, sets scanning status
- `mark_scan_completed(db, library_id) -> None`
- Scan ManagedTasks dispatched with `on_complete=None` — NO POST-SCAN HOOK EXISTS
- Must add `on_complete` to `LibraryScanMixin.start_full_scan`
