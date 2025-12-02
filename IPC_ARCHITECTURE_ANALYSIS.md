# Inter-Process Communication Architecture Analysis

**Date:** December 2, 2025  
**Context:** Understanding how worker processes communicate with main application

---

## Current State: Workers as Threads (WRONG)

### What exists now:
```python
class BaseWorker(threading.Thread):  # ❌ Should be Process
    def __init__(self, ..., event_broker: StateBroker, ...):
        self._event_broker = event_broker  # Direct Python object reference
```

**Problem:** This ONLY works because workers are threads in the same process. When workers become separate processes, `event_broker` object references won't work.

---

## Current Event Communication

### `StateBroker` (event_broker_comp.py)
- **Type:** Thread-safe in-memory state manager
- **Pattern:** Direct method calls with threading locks
- **Storage:** Python dicts with `threading.Lock()`

```python
class StateBroker:
    def __init__(self):
        self._lock = threading.Lock()
        self._queue_state = {...}
        self._jobs_state = {...}
        self._worker_state = {...}
    
    def update_queue_state(self, **kwargs):
        with self._lock:
            self._queue_state.update(kwargs)
            self._broadcast_to_topic(...)
```

### How workers currently use it:
```python
# In BaseWorker._process_job() - worker thread
self._event_broker.update_job_state(job_id, status="running")
self._event_broker.update_queue_state(pending=5, running=1)
```

**This is direct method calls** - only works in same process!

---

## What Services Were Trying to Do with `worker` Parameter

### RecalibrationService
```python
def enqueue_file(self, file_path: str) -> int:
    if self.worker is None or not self.worker.is_alive():
        raise RuntimeError("RecalibrationWorker is not available")
    # Then enqueue...
```

**Intent:** Check if worker process is running before accepting queue jobs.

**Problem:** 
- `worker` is always `None` in current app.py
- Should be asking WorkersCoordinator, not holding worker reference
- Services shouldn't know about worker lifecycle

### LibraryService
```python
def get_library_scan_status(self) -> LibraryScanStatusResult:
    enabled = self.worker is not None
    # Return status with enabled flag
```

**Intent:** Report if scanner worker is available.

**Problem:**
- `worker` is always `None`
- Should ask WorkersCoordinator for worker status
- Services don't need direct worker access

---

## The Right IPC Architecture for Processes

When workers become `multiprocessing.Process`, we need proper IPC:

### Option 1: Database as IPC (SIMPLEST) ⭐ RECOMMENDED

**Workers write to DB:**
```python
# Worker process writes state to DB meta table
self.db.meta.set(f"worker:{self.worker_id}:current_file", path)
self.db.meta.set(f"worker:{self.worker_id}:status", "processing")
```

**Main app reads from DB:**
```python
# StateBroker polls DB and broadcasts to SSE clients
current_file = db.meta.get(f"worker:{worker_id}:current_file")
```

**Benefits:**
- ✅ Already have DB connection in both processes
- ✅ Simple - just key/value writes
- ✅ Persistent across crashes
- ✅ No new infrastructure needed

**Drawbacks:**
- ⚠️ Adds DB writes during processing
- ⚠️ StateBroker needs polling thread

---

### Option 2: Multiprocessing Queue (MODERATE)

**Worker process sends events:**
```python
# In worker process
self.event_queue.put({
    "type": "job_status",
    "job_id": 123,
    "status": "running",
})
```

**Main process receives:**
```python
# In WorkersCoordinator or StateBroker
while not event_queue.empty():
    event = event_queue.get_nowait()
    state_broker.update_job_state(**event)
```

**Benefits:**
- ✅ Fast - no DB overhead
- ✅ Built into Python multiprocessing
- ✅ Type-safe with dicts/dataclasses

**Drawbacks:**
- ⚠️ Need to pass queue to each worker process
- ⚠️ Need consumer thread in main process
- ⚠️ Lost on crash (not persistent)

---

### Option 3: Shared Memory/Manager (COMPLEX)

**Using multiprocessing.Manager:**
```python
# In main process
manager = multiprocessing.Manager()
shared_state = manager.dict()

# In worker process
shared_state[f"worker_{self.worker_id}"] = {"status": "running"}
```

**Benefits:**
- ✅ Direct shared state access
- ✅ No polling needed

**Drawbacks:**
- ❌ Manager process overhead
- ❌ Serialization overhead
- ❌ Complex error handling
- ❌ Lost on crash

---

## Recommended Architecture

### Phase 1: Convert Workers to Processes + DB IPC

```python
class BaseWorker(multiprocessing.Process):  # ✅ Not Thread
    def __init__(
        self,
        name: str,
        queue_type: QueueType,
        process_fn: Callable,
        db: Database,
        worker_id: int = 0,
        interval: int = 2,
    ):
        # NO event_broker parameter - use DB instead
        super().__init__(daemon=True, name=f"{name}-{worker_id}")
        self.db = db
        self.queue_type = queue_type  # "tag", "library", or "calibration"
        self.worker_id = worker_id  # Unique ID within this queue type
        ...
    
    def _publish_job_state(self, job_id: int, path: str, status: str):
        """Publish job state to DB meta for main process to read."""
        self.db.meta.set(f"job:{job_id}:status", status)
        self.db.meta.set(f"job:{job_id}:path", path)
        # Include queue_type in key to distinguish multiple workers per queue
        self.db.meta.set(f"worker:{self.queue_type}:{self.worker_id}:current_job", job_id)
```

### Phase 2: StateBroker Polls DB

```python
class StateBroker:
    def __init__(self, db: Database, worker_counts: dict[str, int]):
        """
        Initialize with worker counts per queue type.
        
        Args:
            db: Database instance
            worker_counts: {"tag": 2, "library": 10, "calibration": 5}
        """
        self.db = db
        self.worker_counts = worker_counts
        self._poll_thread = threading.Thread(target=self._poll_worker_state)
        self._poll_thread.start()
    
    def _poll_worker_state(self):
        """Poll DB for worker state updates every 0.5s."""
        while not self._shutdown:
            # Poll all tagger workers
            for worker_id in range(self.worker_counts["tag"]):
                current_job = self.db.meta.get(f"worker:tag:{worker_id}:current_job")
                if current_job:
                    status = self.db.meta.get(f"job:{current_job}:status")
                    # Broadcast to SSE clients
                    self._broadcast_to_topic(...)
            
            # Poll all scanner workers
            for worker_id in range(self.worker_counts["library"]):
                current_job = self.db.meta.get(f"worker:library:{worker_id}:current_job")
                # ... same pattern
            
            # Poll all recalibration workers
            for worker_id in range(self.worker_counts["calibration"]):
                current_job = self.db.meta.get(f"worker:calibration:{worker_id}:current_job")
                # ... same pattern
            
            time.sleep(0.5)
```

### Phase 3: Services Ask Coordinator, Not Workers

```python
# RecalibrationService - BEFORE (wrong)
def enqueue_file(self, file_path: str) -> int:
    if self.worker is None or not self.worker.is_alive():
        raise RuntimeError(...)

# RecalibrationService - AFTER (correct)
def enqueue_file(self, file_path: str) -> int:
    # Just enqueue - coordinator/workers handle availability
    return enqueue_file(self.db, file_path, queue_type="calibration")

# If need to check worker status, ask coordinator via app context:
# workers_coordinator = app.get_service("workers")
# if not workers_coordinator.is_worker_alive("recalibration"):
#     raise RuntimeError(...)
```

---

## Migration Path

### Step 1: Remove `worker` from Services ✅ DO NOW
- Remove `worker` parameter from `LibraryService.__init__`
- Remove `worker` parameter from `RecalibrationService.__init__`
- Remove all `self.worker` checks from service methods
- Services should just enqueue work - coordinator manages workers

### Step 2: Add DB-based IPC to BaseWorker ⏳ DO NEXT
- Keep workers as threads temporarily
- Replace `event_broker` direct calls with `db.meta.set()` writes
- Update StateBroker to poll DB instead of direct updates
- Verify SSE still works

### Step 3: Convert Workers to Processes ⏳ DO AFTER
- Change `BaseWorker(threading.Thread)` → `BaseWorker(multiprocessing.Process)`
- Remove `event_broker` parameter entirely
- Update app.py to start worker processes
- Test CUDA isolation

### Step 4: Optional - Upgrade to Queue IPC 🔮 FUTURE
- If DB polling is too slow, replace with multiprocessing.Queue
- This is an optimization, not required

---

## Key Insights

### Why services had `worker` parameters:
- **Intent:** Check worker availability before enqueueing
- **Reality:** Always `None`, never worked
- **Fix:** Remove them - services shouldn't manage worker lifecycle

### Why event_broker worked:
- **Current:** Workers are threads in same process, share memory
- **Future:** Workers are processes, need real IPC
- **Solution:** DB meta table as message bus

### Why DB IPC is best:
- Already have DB in both processes
- Simple key/value writes
- Persistent (survives crashes)
- No new dependencies
- Good enough performance for status updates

---

## Final Architecture

```
Main Process (FastAPI)
├─ StateBroker (polls DB for ALL workers across all queue types)
├─ WorkerSystemService (starts/stops worker processes)
│   ├─ start_tagger_workers(count=2)      # 1-2 processes (ML heavy)
│   ├─ start_scanner_workers(count=10)    # Many processes (I/O bound)
│   └─ start_recalibration_workers(count=5)  # Many processes (CPU light)
└─ Services (enqueue jobs, query status)
      ↕ (DB meta table)
Worker Processes (17 total in this example):
├─ TaggerWorker-0 ─┐
├─ TaggerWorker-1 ─┘─→ both poll tag_queue
├─ ScannerWorker-0 ─┐
├─ ScannerWorker-1 ─┤
├─ ScannerWorker-2 ─┤
├─ ... (7 more)     ├─→ all poll library_queue
├─ ScannerWorker-9 ─┘
├─ RecalibrationWorker-0 ─┐
├─ RecalibrationWorker-1 ─┤
├─ RecalibrationWorker-2 ─┼─→ all poll calibration_queue
├─ RecalibrationWorker-3 ─┤
└─ RecalibrationWorker-4 ─┘
```

**All IPC happens through DB meta table - simple, reliable, works.**

**Key insight:** Multiple workers can safely poll the same queue because DB dequeue operations are atomic. Each worker gets a unique job, no race conditions.
