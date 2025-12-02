# Worker Refactoring Plan - December 2, 2025

**Status:** Planning phase - architectural issues identified, solutions proposed  
**Goal:** Simplify worker architecture and fix service layer organization

---

## Key Findings

### 1. Worker Architecture is Overcomplicated

**Current state:**
- 3 coordinator files doing overlapping work
- Thread pools wrapping process pools wrapping work (4 layers deep!)
- Workers are `threading.Thread` but should be `multiprocessing.Process` for CUDA

**Root cause:**
- Confusion between thread-based queue polling vs process-based CPU work
- Each worker thread polls queue → submits to process pool → waits (wasted parallelism)

**What should be:**
- Multiple worker processes per queue type (configurable count):
  - 1-2 TaggerWorker processes polling tag_queue
  - Many ScannerWorker processes polling library_queue (scanning is I/O heavy)
  - Many RecalibrationWorker processes polling calibration_queue (CPU light)
- Each worker polls its queue and processes files synchronously in its process
- Multiple workers can poll same queue safely (DB handles atomicity)
- WorkerSystemService manages all worker processes (non-blocking for main app)

### 2. Inter-Process Communication Problem

**Current:** Workers use `event_broker.update_*()` direct method calls
- Only works because workers are threads (same memory space)
- Won't work when workers become processes

**Solution:** Use DB for IPC and health monitoring
- Workers write: `db.meta.set(f"worker:{queue_type}:{worker_id}:status", "processing")`
- StateBroker reads: `db.meta.get(f"worker:{queue_type}:{worker_id}:status")` and broadcasts to SSE
- Simple, persistent, already have DB in both processes
- Works for N workers per queue type (each has unique worker_id)

**IPC = Inter-Process Communication** (how separate processes talk)

### 2.5. Health Monitoring & Process Management

**Current:** `health_monitor_svc.py` checks thread liveness via `worker.is_alive()`
- Only works for threads in same process
- No persistent health state
- No restart tracking
- No bidirectional health checks

**New Design:** DB-based health table with bidirectional heartbeats
- **Health table schema:**
  ```sql
  CREATE TABLE health (
      component TEXT PRIMARY KEY,           -- "app" or "worker:tag:0" (unique per component)
      last_heartbeat INTEGER NOT NULL,      -- timestamp_ms
      status TEXT NOT NULL,                 -- "healthy", "starting", "stopping", "crashed", "failed"
      restart_count INTEGER DEFAULT 0,      -- how many times restarted
      last_restart INTEGER,                 -- timestamp_ms of last restart
      pid INTEGER,                          -- process ID
      current_job INTEGER,                  -- current job_id (for workers)
      exit_code INTEGER,                    -- process exit code if crashed
      metadata TEXT                         -- JSON for extra info
  );
  
  -- Each process owns exactly ONE row (component is PRIMARY KEY)
  -- Table is wiped on app startup and shutdown (ephemeral runtime state)
  ```

- **Lifecycle management:**
  - **App startup:** `DELETE FROM health; DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%';`
  - **App shutdown:** `DELETE FROM health; DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%';`
  - Each component (app or worker) writes to its own row only
  - Workers use exit codes: 0=success, 1=error, 2=fatal config error, 3=unrecoverable

- **Bidirectional heartbeats:**
  - Main app writes: `health["app"]` every 5s
  - Each worker writes: `health[f"worker:{queue_type}:{worker_id}"]` every 5s
  - WorkerSystemService monitors worker heartbeats, restarts if stale (>30s)
  - External monitoring can check app heartbeat to detect hung main process

- **Restart backoff:**
  - Track `restart_count` per worker
  - Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 60s
  - After 5 rapid restarts (< 5 min each), mark as "failed" and stop trying
  - Check `exit_code` - if fatal (e.g., 2=config error), don't restart
  - Admin can manually reset restart count via API

- **Benefits:**
  - Detect hung workers (heartbeat timeout)
  - Detect crashed workers (process exit)
  - Automatic restart with backoff
  - Avoid restart loops for permanently broken workers
  - External monitoring can check app health
  - Clean state on startup (no stale data from previous runs)
  - Exit codes prevent restarting permanently broken workers

### 3. Services Layer is Mixed Domain + Infrastructure

**Current `services/` contains:**
- Domain services (analytics, calibration, library, recalibration, navidrome)
- Infrastructure services (config, keys, health monitor, workers, coordinators)

**Problem:** All mixed together, unclear what depends on what

**Solution:** Split into subdirectories:
```
services/
├── domain/          (business logic)
│   ├── analytics_svc.py
│   ├── calibration_svc.py
│   ├── library_svc.py
│   ├── recalibration_svc.py
│   └── navidrome_svc.py
│
└── infrastructure/  (runtime plumbing)
    ├── config_svc.py
    ├── keys_svc.py
    ├── health_monitor_svc.py
    ├── info_svc.py
    ├── worker_system_svc.py
    └── workers/
        ├── base.py
        ├── tagger.py
        ├── scanner.py
        └── recalibration.py
```

### 4. Dead Code in Domain Services

**LibraryService and RecalibrationService have `worker` parameters:**
```python
def __init__(self, db, cfg, worker: Worker | None = None):
    self.worker = worker  # Always None, never used
```

**Why this existed:**
- Attempted to check `worker.is_alive()` before enqueueing jobs
- Wrong approach: domain services shouldn't manage worker lifecycle

**Fix:** Remove `worker` parameters entirely
- Domain services just enqueue jobs to DB
- WorkerSystemService manages worker lifecycle
- Interaction is indirect via DB queue tables

---

## Refactoring Plan

### Phase 1: Clean Up Services Layer ✅ DO FIRST

**1.1 Split services into subdirectories**
```bash
mkdir nomarr/services/domain
mkdir nomarr/services/infrastructure
```

**1.2 Move domain services**
```bash
mv nomarr/services/analytics_svc.py nomarr/services/domain/
mv nomarr/services/calibration_svc.py nomarr/services/domain/
mv nomarr/services/library_svc.py nomarr/services/domain/
mv nomarr/services/recalibration_svc.py nomarr/services/domain/
mv nomarr/services/navidrome_svc.py nomarr/services/domain/
```

**1.3 Move infrastructure services**
```bash
mv nomarr/services/config_svc.py nomarr/services/infrastructure/
mv nomarr/services/keys_svc.py nomarr/services/infrastructure/
mv nomarr/services/health_monitor_svc.py nomarr/services/infrastructure/
mv nomarr/services/info_svc.py nomarr/services/infrastructure/
mv nomarr/services/workers_coordinator_svc.py nomarr/services/infrastructure/worker_system_svc.py
mv nomarr/services/workers/ nomarr/services/infrastructure/workers/
```

**1.4 Delete overcomplicated coordinators**
```bash
rm nomarr/services/coordinator_svc.py
rm nomarr/services/worker_pool_svc.py
rm nomarr/services/processing_backends.py  # Maybe keep, TBD
```

**1.5 Update imports everywhere**
- `from nomarr.services.analytics_svc import` → `from nomarr.services.domain.analytics_svc import`
- `from nomarr.services.config_svc import` → `from nomarr.services.infrastructure.config_svc import`
- `from nomarr.services.workers_coordinator_svc import WorkersCoordinator` → `from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService`

**1.6 Update `services/__init__.py`**
- Export from `domain/` and `infrastructure/` subdirectories
- Maintain backward compatibility if needed

---

### Phase 2: Remove Dead Worker Parameters ✅ DO SECOND

**2.1 Remove from LibraryService**
```python
# Before
def __init__(self, db: Database, cfg: LibraryRootConfig, worker: LibraryScanWorker | None = None):
    self.worker = worker

# After
def __init__(self, db: Database, cfg: LibraryRootConfig):
    # No worker parameter
```

**2.2 Remove from RecalibrationService**
```python
# Before
def __init__(self, database: Database, worker: RecalibrationWorker | None = None, library_service: LibraryService | None = None):
    self.worker = worker

# After
def __init__(self, database: Database, library_service: LibraryService | None = None):
    # No worker parameter
```

**2.3 Remove all `self.worker.is_alive()` checks**
- Replace with direct queue operations
- Or query WorkerSystemService for worker status if needed

**2.4 Update app.py constructor calls**
```python
# Before
library_service = LibraryService(db=self.db, cfg=library_cfg, worker=None)
recalibration_service = RecalibrationService(database=self.db, worker=None, library_service=library_service)

# After
library_service = LibraryService(db=self.db, cfg=library_cfg)
recalibration_service = RecalibrationService(database=self.db, library_service=library_service)
```

---

### Phase 3: Implement DB-based IPC ⏳ DO THIRD

**IMPORTANT:** Workers will need their own database connections. Pass `db_path` (string) to workers, not `db` (Database object). Each worker creates its own `Database(db_path)` connection in its `__init__` or `run()` method. This is critical for multiprocessing safety.

**3.1 Create health table schema**
```sql
CREATE TABLE IF NOT EXISTS health (
    component TEXT PRIMARY KEY,           -- "app" or "worker:tag:0" (unique per component)
    last_heartbeat INTEGER NOT NULL,      -- timestamp_ms
    status TEXT NOT NULL,                 -- "healthy", "starting", "stopping", "crashed", "failed"
    restart_count INTEGER DEFAULT 0,      -- how many times restarted
    last_restart INTEGER,                 -- timestamp_ms of last restart
    pid INTEGER,                          -- process ID
    current_job INTEGER,                  -- current job_id (for workers)
    exit_code INTEGER,                    -- process exit code if crashed (0=success, 1=error, 2=fatal, 3=unrecoverable)
    metadata TEXT                         -- JSON for extra info
);

-- Each component owns exactly ONE row (component is PRIMARY KEY)
-- Table is ephemeral - wiped on app startup and shutdown
```

**Add to Application.start():**
```python
def start(self):
    # Clean ephemeral state from previous runs
    logging.info("[Application] Cleaning ephemeral runtime state...")
    self.db.execute("DELETE FROM health")
    self.db.execute("DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%'")
    self.db.commit()
    
    # ... rest of startup
```

**Add to Application.stop():**
```python
def stop(self):
    # ... stop workers, etc ...
    
    # Clean ephemeral state
    logging.info("[Application] Cleaning ephemeral runtime state...")
    self.db.execute("DELETE FROM health")
    self.db.execute("DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%'")
    self.db.commit()
    
    self._running = False
```

**3.2 Update BaseWorker to write heartbeat to health table**
```python
class BaseWorker(threading.Thread):  # Still Thread for now
    def __init__(self, name, queue_type, process_fn, db_path: str, worker_id, interval):
        # Each worker creates its own DB connection (critical for multiprocessing)
        from nomarr.persistence.db import Database
        self.db = Database(db_path)
        self.queue_type = queue_type
        self.worker_id = worker_id
        self.component_id = f"worker:{queue_type}:{worker_id}"
        self._heartbeat_interval = 5  # seconds
        self._last_heartbeat = 0
        self._current_job_id = None
        ...
    
    def _update_heartbeat(self):
        """Write heartbeat to health table (UPSERT to single row)."""
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_heartbeat >= (self._heartbeat_interval * 1000):
            # Each worker owns exactly ONE row (component is PRIMARY KEY)
            self.db.execute("""
                INSERT INTO health (component, last_heartbeat, status, pid, current_job)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    last_heartbeat=excluded.last_heartbeat,
                    status=excluded.status,
                    current_job=excluded.current_job
            """, (self.component_id, now_ms, "healthy", os.getpid(), self._current_job_id))
            self.db.commit()
            self._last_heartbeat = now_ms
    
    def run(self):
        """Main worker loop with heartbeat and exit codes."""
        exit_code = 0
        
        try:
            # Mark starting (UPSERT to single row)
            self.db.execute("""
                INSERT INTO health (component, last_heartbeat, status, pid, restart_count)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(component) DO UPDATE SET
                    last_heartbeat=excluded.last_heartbeat,
                    status=excluded.status,
                    pid=excluded.pid
            """, (self.component_id, int(time.time() * 1000), "starting", os.getpid()))
            self.db.commit()
            
            while not self._shutdown:
                try:
                    self._update_heartbeat()
                    self._poll_and_process()
                    time.sleep(self.interval)
                except Exception as e:
                    logging.error(f"[{self.name}] Error: {e}")
                    # Non-fatal error, continue
                    exit_code = 1
        
        except ConfigurationError as e:
            # Fatal configuration error - don't restart
            logging.error(f"[{self.name}] Fatal config error: {e}")
            exit_code = 2
            self.db.execute(
                "UPDATE health SET status=?, exit_code=?, metadata=? WHERE component=?",
                ("failed", exit_code, str(e), self.component_id)
            )
            self.db.commit()
        
        except UnrecoverableError as e:
            # Unrecoverable error - don't restart
            logging.error(f"[{self.name}] Unrecoverable error: {e}")
            exit_code = 3
            self.db.execute(
                "UPDATE health SET status=?, exit_code=?, metadata=? WHERE component=?",
                ("failed", exit_code, str(e), self.component_id)
            )
            self.db.commit()
        
        finally:
            # Mark stopping
            self.db.execute(
                "UPDATE health SET status=?, exit_code=? WHERE component=?",
                ("stopping", exit_code, self.component_id)
            )
            self.db.commit()
            
            # Note: Row stays in DB for monitoring to detect exit
            # Will be cleaned up on next app startup
    
    def _publish_job_state(self, job_id: int, path: str, status: str):
        """Write job state to DB meta table."""
        self._current_job_id = job_id if status == "running" else None
        self.db.meta.set(f"job:{job_id}:status", status)
        self.db.meta.set(f"job:{job_id}:path", path)
        self.db.meta.set(f"worker:{self.queue_type}:{self.worker_id}:current_job", job_id)
```

**3.3 Update StateBroker to poll DB (meta + health)**
```python
class StateBroker:
    def __init__(self, db: Database, worker_counts: dict[str, int]):
        self.db = db
        self.worker_counts = worker_counts
        self._poll_thread = threading.Thread(target=self._poll_worker_state, daemon=True)
        self._poll_thread.start()
    
    def _poll_worker_state(self):
        """Poll DB for worker state updates every 0.5s."""
        while not self._shutdown:
            # Poll job states from meta table
            for queue_type, count in self.worker_counts.items():
                for worker_id in range(count):
                    current_job = self.db.meta.get(f"worker:{queue_type}:{worker_id}:current_job")
                    if current_job:
                        status = self.db.meta.get(f"job:{current_job}:status")
                        path = self.db.meta.get(f"job:{current_job}:path")
                        self._broadcast_to_topic("queue:jobs", {
                            "type": "job_update",
                            "job": {"id": current_job, "status": status, "path": path, "worker_id": worker_id}
                        })
            
            # Poll worker health from health table
            worker_health = self.db.health.get_all_workers()
            self._broadcast_to_topic("system:health", {
                "type": "health_update",
                "workers": worker_health
            })
            
            time.sleep(0.5)
```

**3.4 Add app-level heartbeat**
```python
# In Application class
def _start_app_heartbeat(self):
    """Start background thread to write app heartbeat (single row)."""
    def heartbeat_loop():
        while self._running:
            # App owns exactly ONE row (component="app")
            self.db.execute("""
                INSERT INTO health (component, last_heartbeat, status, pid)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    last_heartbeat=excluded.last_heartbeat,
                    status=excluded.status
            """, ("app", int(time.time() * 1000), "healthy", os.getpid()))
            self.db.commit()
            time.sleep(5)
    
    self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    self._heartbeat_thread.start()

def start(self):
    # Clean ephemeral state from previous runs
    logging.info("[Application] Cleaning ephemeral runtime state...")
    self.db.execute("DELETE FROM health")
    self.db.execute("DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%'")
    self.db.commit()
    
    # ... existing startup code ...
    
    # Start app heartbeat
    self._start_app_heartbeat()
    
    # ... rest of startup
```

**3.5 Update app.py to create StateBroker with DB**
```python
# Before
self.event_broker = StateBroker()

# After
worker_counts = {
    "tag": self.tagger_worker_count,       # 1-2 workers (ML is heavy)
    "library": self.scanner_worker_count,  # Many workers (I/O bound scanning)
    "calibration": self.recalibration_worker_count,  # Many workers (CPU light)
}
self.event_broker = StateBroker(db=self.db, worker_counts=worker_counts)
```

**3.6 Update worker constructors**
```python
# Before
TaggerWorker(db, queue, backend, event_broker, interval, worker_id)

# After
TaggerWorker(db_path, queue, backend, worker_id, interval)  # Pass db_path, not db connection
# Each worker creates its own Database connection in __init__
```

---

### Phase 4: Convert Workers to Processes ⏳ DO FOURTH

**CRITICAL:** Each process must create its own database connection. Never share a `Database` object across processes.

**4.1 Change BaseWorker inheritance**
```python
# Before
class BaseWorker(threading.Thread, Generic[TResult]):

# After
class BaseWorker(multiprocessing.Process, Generic[TResult]):
    def __init__(self, name, queue_type, process_fn, db_path: str, worker_id, interval):
        super().__init__(daemon=True, name=f"{name}-{worker_id}")
        # Use multiprocessing.Event instead of threading.Event
        self._stop_event = multiprocessing.Event()
        # Store db_path, create connection in run()
        self.db_path = db_path
        self.db = None
    
    def run(self):
        """Create DB connection in child process (CRITICAL for multiprocessing)."""
        from nomarr.persistence.db import Database
        self.db = Database(self.db_path)  # Each process gets its own connection
        
        # Now run normal worker loop with heartbeats...
        exit_code = 0
        try:
            self.db.execute("""
                INSERT INTO health (component, last_heartbeat, status, pid, restart_count)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(component) DO UPDATE SET
                    last_heartbeat=excluded.last_heartbeat,
                    status=excluded.status,
                    pid=excluded.pid
            """, (self.component_id, int(time.time() * 1000), "starting", os.getpid()))
            self.db.commit()
            
            while not self._shutdown:
                self._update_heartbeat()
                self._poll_and_process()
                time.sleep(self.interval)
        except Exception as e:
            logging.error(f"[{self.name}] Error: {e}")
            exit_code = 1
        finally:
            self.db.execute(
                "UPDATE health SET status=?, exit_code=? WHERE component=?",
                ("stopped", exit_code, self.component_id)
            )
            self.db.commit()
            self.db.close()  # Close connection on exit
```

**4.2 Update WorkerSystemService to manage processes with health monitoring**
```python
class WorkerSystemService:
    def __init__(self, db, tagger_count=2, scanner_count=10, recalibration_count=5):
        """
        Initialize worker system with health monitoring.
        """
        self.db = db
        self.tagger_count = tagger_count
        self.scanner_count = scanner_count
        self.recalibration_count = recalibration_count
        
        self.tagger_workers: list[TaggerWorker] = []
        self.scanner_workers: list[LibraryScanWorker] = []
        self.recalibration_workers: list[RecalibrationWorker] = []
        
        # Start health monitor thread
        self._monitor_thread = threading.Thread(target=self._monitor_worker_health, daemon=True)
        self._monitor_thread.start()
    
    def _monitor_worker_health(self):
        """Monitor worker heartbeats and restart if needed."""
        while not self._shutdown:
            now_ms = int(time.time() * 1000)
            stale_threshold = 30 * 1000  # 30 seconds
            
            # Check all workers
            for queue_type, workers in [
                ("tag", self.tagger_workers),
                ("library", self.scanner_workers),
                ("calibration", self.recalibration_workers),
            ]:
                for worker in workers:
                    component_id = f"worker:{queue_type}:{worker.worker_id}"
                    health = self.db.health.get(component_id)
                    
                    if not health:
                        # Worker never started - skip
                        continue
                    
                    # Check if heartbeat is stale
                    if (now_ms - health["last_heartbeat"]) > stale_threshold:
                        logging.warning(f"Worker {component_id} heartbeat stale, restarting...")
                        self._restart_worker(worker, queue_type, component_id)
                    
                    # Check if process died
                    elif not worker.is_alive():
                        logging.warning(f"Worker {component_id} process died, restarting...")
                        self._restart_worker(worker, queue_type, component_id)
            
            time.sleep(10)  # Check every 10 seconds
    
    def _restart_worker(self, worker: BaseWorker, queue_type: str, component_id: str):
        """Restart a worker with exponential backoff."""
        # Get current restart count
        health = self.db.health.get(component_id)
        restart_count = health.get("restart_count", 0) if health else 0
        last_restart = health.get("last_restart", 0) if health else 0
        
        now_ms = int(time.time() * 1000)
        
        # Check if restarting too frequently (< 5 min)
        if restart_count >= 5 and (now_ms - last_restart) < (5 * 60 * 1000):
            logging.error(f"Worker {component_id} failed too many times, giving up")
            self.db.health.update(
                component=component_id,
                status="failed",
                metadata=f"Failed after {restart_count} restart attempts"
            )
            return
        
        # Calculate backoff delay: 1s, 2s, 4s, 8s, 16s, max 60s
        backoff_delay = min(2 ** restart_count, 60)
        logging.info(f"Waiting {backoff_delay}s before restarting {component_id}...")
        time.sleep(backoff_delay)
        
        # Stop old worker
        try:
            worker.stop()
            worker.join(timeout=5)
            if worker.is_alive():
                worker.terminate()
        except Exception as e:
            logging.error(f"Error stopping worker {component_id}: {e}")
        
        # Create new worker (using factory method - implementation specific)
        new_worker = self._create_worker(queue_type, worker.worker_id)
        new_worker.start()
        
        # Update worker list
        self._replace_worker_in_list(queue_type, worker.worker_id, new_worker)
        
        # Update health table
        self.db.health.update(
            component=component_id,
            restart_count=restart_count + 1,
            last_restart=now_ms,
            status="starting"
        )
        
        logging.info(f"Restarted worker {component_id} (restart #{restart_count + 1})")
    
    def start_tagger_workers(self) -> None:
        """Start N tagger worker processes."""
        for i in range(self.tagger_count):
            # Pass db_path, not db connection (workers create their own connections)
            worker = TaggerWorker(db_path=self.db.db_path, worker_id=i, ...)
            worker.start()
            self.tagger_workers.append(worker)
            
            # Initialize health record
            self.db.health.upsert(
                component=f"worker:tag:{i}",
                last_heartbeat=int(time.time() * 1000),
                status="starting",
                pid=worker.pid,
                restart_count=0
            )
    
    # Similar for scanner and recalibration workers...
    
    def stop_all_workers(self) -> None:
        """Stop all worker processes gracefully."""
        all_workers = self.tagger_workers + self.scanner_workers + self.recalibration_workers
        
        # Signal all workers to stop
        for worker in all_workers:
            worker.stop()
        
        # Wait for graceful shutdown with timeout
        for worker in all_workers:
            worker.join(timeout=10)
            if worker.is_alive():
                logging.warning(f"Worker {worker.name} did not stop gracefully, terminating...")
                worker.terminate()
        
        # Mark all as stopped in health table
        for worker in all_workers:
            component_id = f"worker:{worker.queue_type}:{worker.worker_id}"
            self.db.health.update(component=component_id, status="stopped")
    
    def reset_restart_count(self, component_id: str) -> None:
        """Reset restart count for a worker (admin operation)."""
        self.db.health.update(component=component_id, restart_count=0)
        logging.info(f"Reset restart count for {component_id}")
```

**4.3 Update app.py to create worker processes**
```python
# Get worker counts from config (with sensible defaults)
tagger_worker_count = self._config_service.get_worker_count("tagger", default=2)
scanner_worker_count = self._config_service.get_worker_count("scanner", default=10)
recalibration_worker_count = self._config_service.get_worker_count("recalibration", default=5)

# Create processing backends that run in-process (no process pools)
def make_tagger_backend(path: str, force: bool) -> ProcessFileResult:
    """Backend that runs directly in worker process."""
    # Load models once per process (lazy init)
    # Process file synchronously
    return process_file(path, force)

# Create WorkerSystemService
self.worker_system = WorkerSystemService(
    db=self.db,
    tagger_count=tagger_worker_count,
    scanner_count=scanner_worker_count,
    recalibration_count=recalibration_worker_count,
)

# Start all workers
self.worker_system.start_tagger_workers()
self.worker_system.start_scanner_workers()
self.worker_system.start_recalibration_workers()
```

**4.4 Handle CUDA context isolation**
```python
# Set multiprocessing start method to 'spawn' for CUDA
import multiprocessing as mp
mp.set_start_method('spawn', force=True)
```

---

### Phase 5: Simplify Processing Backends ⏳ DO FIFTH

**5.1 Remove process pool wrappers**
- Delete `CoordinatorService` entirely
- Delete `WorkerPoolService` entirely
- Processing backends run directly in worker process

**5.2 Update backends to lazy-load models**
```python
# In processing_backends.py or similar
_tagger_models = None

def tagger_backend(path: str, force: bool) -> ProcessFileResult:
    """Process file with ML tagging. Runs in worker process."""
    global _tagger_models
    if _tagger_models is None:
        # Lazy load models once per process
        _tagger_models = load_ml_models()
    
    # Process synchronously in this process
    return process_file_with_models(path, force, _tagger_models)
```

---

## Success Criteria

After refactoring, we should have:

1. ✅ Clear separation: `services/domain/` vs `services/infrastructure/`
2. ✅ Multiple worker processes per queue type (configurable counts)
3. ✅ Workers communicate via DB meta table IPC with unique keys per worker
4. ✅ Workers write heartbeats to DB health table every 5s
5. ✅ WorkerSystemService monitors health and auto-restarts crashed/hung workers
6. ✅ Exponential backoff prevents restart loops (1s → 60s max)
7. ✅ After 5 rapid restarts, worker marked "failed" and stops restarting
8. ✅ Admin API can reset restart count for manual recovery
9. ✅ Domain services have no worker references
10. ✅ WorkerSystemService owns all worker lifecycle and manages N processes per type
11. ✅ Each worker process has isolated CUDA context
12. ✅ No `CoordinatorService` or `WorkerPoolService` complexity
13. ✅ Queue dequeue is atomic (multiple workers can safely poll same queue)
14. ✅ Bidirectional health monitoring (app + workers write heartbeats)
15. ✅ External monitoring can check app health via DB query

---

## Files to Change

### Move & Rename
- `services/analytics_svc.py` → `services/domain/analytics_svc.py`
- `services/calibration_svc.py` → `services/domain/calibration_svc.py`
- `services/library_svc.py` → `services/domain/library_svc.py`
- `services/recalibration_svc.py` → `services/domain/recalibration_svc.py`
- `services/navidrome_svc.py` → `services/domain/navidrome_svc.py`
- `services/config_svc.py` → `services/infrastructure/config_svc.py`
- `services/keys_svc.py` → `services/infrastructure/keys_svc.py`
- `services/health_monitor_svc.py` → DELETE (replaced by DB health table + WorkerSystemService monitoring)
- `services/info_svc.py` → `services/infrastructure/info_svc.py`
- `services/workers_coordinator_svc.py` → `services/infrastructure/worker_system_svc.py`
- `services/workers/` → `services/infrastructure/workers/`

### Delete
- `services/coordinator_svc.py`
- `services/worker_pool_svc.py`
- `services/health_monitor_svc.py` (replaced by DB health table)
- Possibly `services/processing_backends.py` (or refactor heavily)

### Modify
- `services/infrastructure/workers/base.py` - Change to Process, add DB IPC + health heartbeat
- `services/infrastructure/workers/tagger.py` - Remove event_broker param
- `services/infrastructure/workers/scanner.py` - Remove event_broker param
- `services/infrastructure/workers/recalibration.py` - Remove event_broker param
- `services/domain/library_svc.py` - Remove worker param
- `services/domain/recalibration_svc.py` - Remove worker param
- `components/events/event_broker_comp.py` - Add DB polling for meta + health
- `persistence/db.py` - Add `health` table operations
- `app.py` - Update all imports, worker creation, add app heartbeat
- `services/__init__.py` - Update exports
- All interfaces - Update imports

---

## Risk Assessment

**Low risk:**
- Phase 1 (file moves) - mostly mechanical, can test incrementally
- Phase 2 (remove dead params) - code literally never used

**Medium risk:**
- Phase 3 (DB IPC) - changes communication pattern but workers still threads
- Can test SSE still works before moving to processes

**High risk:**
- Phase 4 (convert to processes) - changes fundamental worker architecture
- CUDA context isolation might reveal issues
- DB connection sharing across processes needs testing

**Recommendation:** Do phases 1-3 first, test thoroughly, then phase 4 in separate session.

---

## Notes

## Notes

- Health table tracks all components (app + workers) with heartbeats
- Heartbeat timeout = 30s (workers write every 5s, so 6x buffer)
- Restart backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
- Rapid restart detection: 5 restarts within 5 minutes = permanent failure
- Admin can reset restart_count via API to manually recover failed workers
- StateBroker polling every 0.5s adds minimal DB load (scales with worker count)
- Multiprocessing requires picklable objects - check all worker parameters
- Windows might need special multiprocessing handling vs Linux/Docker
- **Worker count guidelines:**
  - Taggers: 1-2 (ML inference is GPU/CPU heavy, CUDA context overhead)
  - Scanners: 10+ (I/O bound - filesystem traversal, many small operations)
  - Recalibration: 5+ (CPU light - just applying calibration values, fast per file)
- DB queue dequeue is already atomic - multiple workers polling same queue is safe
- Health table enables external monitoring (e.g., Docker healthcheck, Prometheus)

---

## References

- `WORKER_ARCHITECTURE_ANALYSIS.md` - Original problem analysis
- `IPC_ARCHITECTURE_ANALYSIS.md` - IPC solution details
- `docs/NAMING_STANDARDS.md` - Service naming conventions
- `docs/SERVICES.md` - Service layer guidelines (needs update)
