# Worker Normalization Refactoring Plan

## Current State (Problems)

### 1. Inconsistent Worker Construction
- **TaggerWorker**: Created by `WorkerService._start_new_workers()`, then `worker.process_fn` mutated externally
- **LibraryScanWorker**: Creates its own `ScanQueue(db)` internally instead of receiving it
- **RecalibrationWorker**: Receives queue properly ✓, but no process pool

### 2. Only Tagger Uses Process Pool
- CoordinatorService wraps `process_file_workflow` in process pool
- Scanner and recalibration run synchronously
- Process pool usage hidden behind `process_fn` override

### 3. WorkerService is Tagger-Specific
- Imports `TaggerWorker` internally
- Assumes `ProcessingQueue` and `CoordinatorService`
- Named generically but not actually generic

## Refactoring Strategy

### Phase 1: Create Processing Backends ✅ DONE
**File**: `nomarr/services/processing_backends.py`

Factory functions to create processing backends with unified signature:
```python
ProcessingBackend = Callable[[str, bool], ProcessFileResult | dict[str, Any]]

- make_coordinator_backend(coordinator) -> ProcessingBackend
- make_tagger_backend(db) -> ProcessingBackend  
- make_scanner_backend(db, namespace, auto_tag, ignore_patterns) -> ProcessingBackend
- make_recalibration_backend(db, models_dir, namespace, version_tag_key, calibrate_heads) -> ProcessingBackend
```

### Phase 2: Update Worker Constructors
**Files**: `nomarr/services/workers/{tagger,scanner,recalibration}.py`

#### TaggerWorker
**Current**:
```python
def __init__(self, db, queue, event_broker, interval, worker_id):
    super().__init__(..., process_fn=self._process, ...)
    
def _process(self, path, force):
    # Uses self.config_service
```

**Target**:
```python
def __init__(self, db, queue, processing_backend, event_broker, interval, worker_id):
    super().__init__(..., process_fn=processing_backend, ...)
    # No more self._process method
```

#### LibraryScanWorker  
**Current**:
```python
def __init__(self, db, event_broker, namespace, interval, worker_id, auto_tag, ignore_patterns):
    scan_queue = ScanQueue(db)  # ❌ Creates queue internally
    super().__init__(..., process_fn=self._process, ...)
    
def _process(self, path, force):
    # Uses self.namespace, self.auto_tag, etc.
```

**Target**:
```python
def __init__(self, db, queue, processing_backend, event_broker, interval, worker_id):
    super().__init__(..., process_fn=processing_backend, ...)
    # Backend captures namespace, auto_tag as closures
```

#### RecalibrationWorker
**Current**:
```python
def __init__(self, db, queue, event_broker, models_dir, namespace, version_tag_key, interval, worker_id, calibrate_heads):
    super().__init__(..., process_fn=self._process, ...)
    self.models_dir = models_dir  # Used in _process
    
def _process(self, path, force):
    # Uses self.models_dir, self.namespace, etc.
```

**Target**:
```python
def __init__(self, db, queue, processing_backend, event_broker, interval, worker_id):
    super().__init__(..., process_fn=processing_backend, ...)
    # Backend captures models_dir, namespace as closures
```

### Phase 3: Create Generic WorkerPoolService
**File**: `nomarr/services/worker_pool_svc.py` (new file, rename from `worker_svc.py`)

```python
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from nomarr.services.workers.base import BaseWorker

TWorker = TypeVar("TWorker", bound=BaseWorker)

@dataclass
class WorkerPoolConfig:
    """Configuration for worker pool (uses global settings)."""
    worker_count: int
    poll_interval: int
    default_enabled: bool

class WorkerPoolService(Generic[TWorker]):
    """
    Generic worker pool manager.
    
    Manages N workers of a given type, all using:
    - Same queue
    - Same processing backend  
    - Same poll interval
    - Global worker_count config
    """
    
    def __init__(
        self,
        db: Database,
        queue: BaseQueue,
        worker_factory: Callable[..., TWorker],
        processing_backend: ProcessingBackend,
        cfg: WorkerPoolConfig,
    ):
        """
        Initialize worker pool.
        
        Args:
            db: Database instance
            queue: Queue for this worker type  
            worker_factory: Constructor (e.g., TaggerWorker, LibraryScanWorker)
            processing_backend: Backend callable for job processing
            cfg: Worker pool configuration
        """
        self.db = db
        self.queue = queue
        self.worker_factory = worker_factory
        self.processing_backend = processing_backend
        self.cfg = cfg
        self.worker_pool: list[TWorker] = []
    
    def is_enabled(self) -> bool:
        """Check if workers are enabled via DB meta."""
        meta = self.db.meta.get("worker_enabled")
        if meta is None:
            return self.cfg.default_enabled
        return bool(meta == "true")
    
    def enable(self) -> None:
        """Enable workers (sets DB meta flag)."""
        self.db.meta.set("worker_enabled", "true")
    
    def disable(self) -> None:
        """Disable workers and wait for idle."""
        self.db.meta.set("worker_enabled", "false")
        self.wait_until_idle(timeout=60)
        self.stop_all_workers()
    
    def start_workers(self, event_broker: Any) -> list[TWorker]:
        """Start worker_count workers using factory and backend."""
        if not self.is_enabled():
            return self.worker_pool
        
        current_count = len([w for w in self.worker_pool if w.is_alive()])
        
        for i in range(current_count, self.cfg.worker_count):
            worker = self.worker_factory(
                db=self.db,
                queue=self.queue,
                processing_backend=self.processing_backend,
                event_broker=event_broker,
                interval=self.cfg.poll_interval,
                worker_id=i,
            )
            worker.start()
            self.worker_pool.append(worker)
        
        return self.worker_pool
    
    def stop_all_workers(self) -> None:
        """Stop all workers gracefully."""
        for worker in self.worker_pool:
            worker.stop()
        for worker in self.worker_pool:
            if worker.is_alive():
                worker.join(timeout=10)
        self.worker_pool = []
    
    def wait_until_idle(self, timeout: int = 60, poll_interval: float = 0.5) -> bool:
        """Wait for all workers to become idle."""
        import time
        start = time.time()
        while (time.time() - start) < timeout:
            any_busy = any(w.is_busy() for w in self.worker_pool if w.is_alive())
            running_count = self.db.tag_queue.queue_stats().get("running", 0)
            if not any_busy and running_count == 0:
                return True
            time.sleep(poll_interval)
        return False
    
    def cleanup_orphaned_jobs(self) -> int:
        """Reset orphaned jobs to pending."""
        jobs_reset = 0
        with self.queue.lock:
            running_job_ids = self.queue.get_running_job_ids()
            for job_id in running_job_ids:
                self.queue.update_job_status(job_id, "pending")
                jobs_reset += 1
        return jobs_reset
    
    def get_status(self) -> dict[str, Any]:
        """Get worker pool status."""
        enabled = self.is_enabled()
        self.worker_pool = [w for w in self.worker_pool if w.is_alive()]
        running = len(self.worker_pool)
        
        return {
            "enabled": enabled,
            "worker_count": self.cfg.worker_count,
            "running": running,
            "workers": [
                {"id": i, "alive": w.is_alive(), "name": w.name}
                for i, w in enumerate(self.worker_pool)
            ],
        }
```

### Phase 4: Update CoordinatorService for Multiple Workflows
**File**: `nomarr/services/coordinator_svc.py`

#### Current Limitation
CoordinatorService is hardcoded to `process_file_workflow` via `process_file_wrapper`.

#### Solution A: Generic Coordinator ✅ PARTIALLY DONE
Make coordinator accept workflow module/function strings:
```python
def __init__(self, cfg, workflow_module: str, workflow_func: str):
    self._wrapper = make_process_wrapper(workflow_module, workflow_func)
```

But workflows have different signatures:
- `process_file_workflow(path, config, db)` ❌
- `scan_single_file_workflow(db, params)` ❌  
- `recalibrate_file_workflow(db, params)` ❌

None match `(path: str, force: bool)` needed by coordinator!

#### Solution B: Create Workflow Wrappers
Create wrapper modules for each workflow that match `(path, force)` signature:

**File**: `nomarr/workflows/processing/process_file_pooled.py`
```python
def process_file_pooled(path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
    """
    Pooled wrapper for process_file_workflow.
    Handles config loading internally for process pool execution.
    """
    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.processing.process_file_wf import process_file_workflow
    
    config_service = ConfigService()
    processor_config = config_service.make_processor_config()
    
    return process_file_workflow(path, config=processor_config, db=None)
```

**File**: `nomarr/workflows/library/scan_single_file_pooled.py`
```python
def scan_single_file_pooled(path: str, force: bool) -> dict[str, Any]:
    """
    Pooled wrapper for scan_single_file_workflow.
    Handles config and DB loading internally for process pool execution.
    """
    from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
    from nomarr.persistence.db import Database
    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow
    
    config_service = ConfigService()
    db = Database(config_service.db_path)  # Each process gets own DB connection
    
    params = ScanSingleFileWorkflowParams(
        file_path=path,
        namespace=config_service.namespace,
        force=force,
        auto_tag=config_service.library_auto_tag,
        ignore_patterns=config_service.library_ignore_patterns,
        library_id=None,
    )
    
    return scan_single_file_workflow(db, params)
```

**File**: `nomarr/workflows/calibration/recalibrate_file_pooled.py`
```python
def recalibrate_file_pooled(path: str, force: bool) -> dict[str, Any]:
    """
    Pooled wrapper for recalibrate_file_workflow.
    Handles config and DB loading internally for process pool execution.
    """
    from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
    from nomarr.persistence.db import Database
    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow
    
    config_service = ConfigService()
    db = Database(config_service.db_path)  # Each process gets own DB connection
    
    params = RecalibrateFileWorkflowParams(
        file_path=path,
        models_dir=config_service.models_dir,
        namespace=config_service.namespace,
        version_tag_key=config_service.version_tag_key,
        calibrate_heads=config_service.calibrate_heads,
    )
    
    recalibrate_file_workflow(db, params)
    return {"status": "success", "path": path}
```

Then create 3 coordinators in `app.py`:
```python
# Tagger coordinator
tagger_coord = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.processing.process_file_pooled",
    workflow_func="process_file_pooled",
)
tagger_coord.start()

# Scanner coordinator  
scanner_coord = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.library.scan_single_file_pooled",
    workflow_func="scan_single_file_pooled",
)
scanner_coord.start()

# Recalibration coordinator
recalib_coord = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.calibration.recalibrate_file_pooled",
    workflow_func="recalibrate_file_pooled",
)
recalib_coord.start()
```

### Phase 5: Wire Everything in app.py
**File**: `nomarr/app.py`

```python
# Load config once
from nomarr.services.config_svc import ConfigService
config_service = ConfigService()

# Create coordinators for all worker types
from nomarr.services.coordinator_svc import CoordinatorConfig, CoordinatorService

coord_cfg = CoordinatorConfig(
    worker_count=config_service.worker_count,
    event_broker=self.event_broker,
)

# Tagger coordinator (process pool)
tagger_coordinator = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.processing.process_file_pooled",
    workflow_func="process_file_pooled",
)
tagger_coordinator.start()

# Scanner coordinator (process pool)
scanner_coordinator = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.library.scan_single_file_pooled",
    workflow_func="scan_single_file_pooled",
)
scanner_coordinator.start()

# Recalibration coordinator (process pool)
recalib_coordinator = CoordinatorService(
    cfg=coord_cfg,
    workflow_module="nomarr.workflows.calibration.recalibrate_file_pooled",
    workflow_func="recalibrate_file_pooled",
)
recalib_coordinator.start()

# Create processing backends
from nomarr.services.processing_backends import make_coordinator_backend

tagger_backend = make_coordinator_backend(tagger_coordinator)
scanner_backend = make_coordinator_backend(scanner_coordinator)
recalib_backend = make_coordinator_backend(recalib_coordinator)

# Create queues
processing_queue = ProcessingQueue(self.db)
scan_queue = ScanQueue(self.db)
recalib_queue = RecalibrationQueue(self.db)

# Create worker pool config (shared by all pools)
from nomarr.services.worker_pool_svc import WorkerPoolConfig, WorkerPoolService

pool_cfg = WorkerPoolConfig(
    worker_count=config_service.worker_count,
    poll_interval=config_service.worker_poll_interval,
    default_enabled=config_service.worker_enabled_default,
)

# Create tagger worker pool
from nomarr.services.workers.tagger import TaggerWorker

tagger_pool = WorkerPoolService(
    db=self.db,
    queue=processing_queue,
    worker_factory=TaggerWorker,
    processing_backend=tagger_backend,
    cfg=pool_cfg,
)
self.workers = tagger_pool.start_workers(event_broker=self.event_broker)

# Create scanner worker pool  
from nomarr.services.workers.scanner import LibraryScanWorker

scanner_pool = WorkerPoolService(
    db=self.db,
    queue=scan_queue,
    worker_factory=LibraryScanWorker,
    processing_backend=scanner_backend,
    cfg=pool_cfg,
)
self.scan_workers = scanner_pool.start_workers(event_broker=self.event_broker)

# Create recalibration worker pool
from nomarr.services.workers.recalibration import RecalibrationWorker

recalib_pool = WorkerPoolService(
    db=self.db,
    queue=recalib_queue,
    worker_factory=RecalibrationWorker,
    processing_backend=recalib_backend,
    cfg=pool_cfg,
)
self.recalib_workers = recalib_pool.start_workers(event_broker=self.event_broker)
```

## End State

### Unified Pattern
Every worker type follows the same pattern:

1. **Coordinator** (process pool) wraps a workflow
2. **Backend** (callable) bridges coordinator → worker
3. **Worker** (thread) polls queue and calls backend
4. **Worker Pool** (service) manages N workers uniformly

### Same Config
All worker pools use:
- Global `worker_count`
- Global `poll_interval`
- Global `worker_enabled` flag

### Same Construction
```python
WorkerPoolService(
    db=db,
    queue=<domain_queue>,
    worker_factory=<DomainWorker>,
    processing_backend=make_coordinator_backend(<domain_coordinator>),
    cfg=shared_pool_cfg,
)
```

### No More Anti-Patterns
- ❌ No more `worker.process_fn` mutation after construction
- ❌ No more workers creating queues internally
- ❌ No more tagger-specific "generic" services
- ✅ All workers use process pools
- ✅ All workers constructed identically
- ✅ Clear separation: coordinator (pool) → backend (callable) → worker (thread) → queue

## Migration Checklist

- [x] Create `processing_backends.py` with backend factories
- [ ] Create pooled workflow wrappers (`*_pooled.py`)
- [ ] Update `CoordinatorService` constructor to accept workflow params
- [ ] Update `TaggerWorker` to accept `processing_backend` in constructor
- [ ] Update `LibraryScanWorker` to accept `queue` and `processing_backend`
- [ ] Update `RecalibrationWorker` to accept `processing_backend`
- [ ] Create `WorkerPoolService` as generic pool manager
- [ ] Update `app.py` to create 3 coordinators
- [ ] Update `app.py` to create 3 worker pools uniformly
- [ ] Update tests to use new constructors
- [ ] Remove old `WorkerService` (rename to `worker_pool_svc.py`)
- [ ] Update `LibraryService` to not import `LibraryScanWorker` directly
- [ ] Update `RecalibrationService` to not import `RecalibrationWorker` directly
- [ ] Verify all workers run in process pools
- [ ] Verify single `worker_count` config applies to all

## Testing Strategy

1. **Unit test each backend factory**
   - Verify signatures match `(path, force) -> ProcessFileResult | dict`
   - Verify closures capture config correctly

2. **Unit test WorkerPoolService**
   - Mock worker factory and backend
   - Test start/stop/wait_until_idle

3. **Integration test each worker type**
   - Verify tagger pool processes files
   - Verify scanner pool scans files
   - Verify recalibration pool recalibrates files
   - All should run in process pools

4. **Integration test global config**
   - Set `worker_count=2`
   - Verify tagger, scanner, recalibration each start 2 workers
   - Set `worker_count=4`
   - Verify each pool scales to 4 workers
