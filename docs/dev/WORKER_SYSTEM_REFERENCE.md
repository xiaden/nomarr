# Worker System Technical Reference

**Last Updated:** 2025-12-05  
**Modules Covered:**
- `nomarr.services.infrastructure.worker_system_svc`
- `nomarr.persistence.database.health_sql`
- `nomarr.components.events.event_broker_comp`
- `nomarr.services.infrastructure.workers.base`

---

## Table of Contents

1. [Overview](#overview)
2. [Worker Process Lifecycle](#worker-process-lifecycle)
3. [Health Table Structure](#health-table-structure)
4. [State Broker and SSE](#state-broker-and-sse)
5. [Pause/Resume Behavior](#pauseresume-behavior)
6. [Restart Logic and Backoff](#restart-logic-and-backoff)
7. [Exit Code Handling](#exit-code-handling)
8. [IPC Architecture](#ipc-architecture)

---

## Overview

Nomarr's worker system manages multiple background worker processes using:
- **Multiprocessing**: Each worker is a separate `multiprocessing.Process` (not threads)
- **Database-based IPC**: Workers communicate via DB tables (health, meta) for multiprocessing safety
- **Health monitoring**: Background thread monitors worker heartbeats and restarts failed workers
- **Event broadcasting**: StateBroker polls DB and broadcasts state updates via SSE

**Key Components:**
- `WorkerSystemService`: Manages worker process pool, health monitoring, restart logic
- `BaseWorker`: Generic worker process that polls queues and processes jobs
- `HealthOperations`: DB persistence for worker health records
- `StateBroker`: SSE event broker with DB polling for multiprocessing IPC

---

## Worker Process Lifecycle

### 1. Spawn

**Trigger:** `WorkerSystemService.start_all_workers()` called on app startup (if `worker_enabled=true` in DB meta).

**Process:**
1. For each queue type (`tag`, `library`, `calibration`), spawn N worker processes:
   - Tagger workers: 2 (ML-heavy, default)
   - Scanner workers: 10 (I/O-bound, default)
   - Calibration workers: 5 (CPU-light, default)

2. Each worker is initialized with:
   - `db_path`: Path to database (each process creates its own connection)
   - `processing_backend`: Injected backend with process logic
   - `event_broker`: Reference to StateBroker (for IPC metadata)
   - `worker_id`: Unique numeric ID within queue type
   - `interval`: Poll interval in seconds (2-5s depending on type)

3. Worker process calls `.start()` → `BaseWorker.run()`:
   - Creates fresh DB connection in child process (critical for multiprocessing)
   - Writes health record: `mark_starting(component="worker:{queue_type}:{id}", pid=<pid>)`
   - Enters main loop

**Component ID Format:** `worker:{queue_type}:{worker_id}`
- Examples: `worker:tag:0`, `worker:library:3`, `worker:calibration:2`

### 2. Heartbeat

**Background Thread:** `WorkerSystemService._monitor_worker_health()` checks health every 10 seconds.

**Worker Heartbeat Behavior:**
- **Interval:** Every 5 seconds (configurable via `_heartbeat_interval`)
- **Method:** `BaseWorker._update_heartbeat()` → `db.health.update_heartbeat()`
- **Fields Updated:**
  - `last_heartbeat`: Current timestamp in milliseconds
  - `status`: `"healthy"` (or `"starting"` during initialization)
  - `current_job`: Job ID being processed (or `None` if idle)

**Health Check Logic:**
```python
# In WorkerSystemService._monitor_worker_health()
now_ms = int(time.time() * 1000)
heartbeat_age = now_ms - last_heartbeat

# Stale heartbeat → restart
if heartbeat_age > HEARTBEAT_STALE_THRESHOLD_MS:  # 30 seconds
    db.health.mark_crashed(component, EXIT_CODE_HEARTBEAT_TIMEOUT, metadata)
    restart_worker()

# Process died → restart
if not worker.is_alive():
    exit_code = worker.exitcode or EXIT_CODE_UNKNOWN_CRASH
    db.health.mark_crashed(component, exit_code, metadata)
    restart_worker()
```

### 3. Termination (Graceful)

**Trigger:** `WorkerSystemService.stop_all_workers()` or worker pause.

**Process:**
1. Main thread calls `worker.stop()` → sets `_stop_event` flag
2. Worker main loop (`BaseWorker.run()`) detects flag and exits loop
3. Worker writes to health table in `finally` block:
   ```python
   db.health.mark_stopping(component=component_id, exit_code=0)
   ```
4. Worker closes DB connection and exits process

**Timeout Handling:**
- Wait `WORKER_STOP_TIMEOUT_SECONDS` (10s) for graceful shutdown
- If still alive, call `worker.terminate()` (SIGTERM)
- Wait `WORKER_TERMINATE_TIMEOUT_SECONDS` (2s) for termination

### 4. Restart (Automatic)

**Trigger:** Health monitor detects stale heartbeat or dead process.

**Process:**
1. Health monitor calls `_schedule_restart()` (spawns background thread to avoid blocking)
2. Increment restart count: `db.health.increment_restart_count(component)`
3. Check restart limits:
   - If `restart_count >= 5` within 5-minute window → mark as `"failed"`, stop restarting
4. Calculate exponential backoff delay: `min(2^restart_count, 60)` seconds
5. Sleep for backoff delay
6. Stop old worker process (terminate if needed)
7. Create new worker with same `worker_id` and queue type
8. Start new worker: `new_worker.start()`
9. Wait briefly (max 500ms) for OS to assign PID
10. Write health record: `db.health.mark_starting(component, pid=<pid>)`

**Restart Count Semantics:**
- Persists across restarts (stored in health table)
- Reset only via manual admin operation: `reset_restart_count(component_id)`
- Used for exponential backoff and failure threshold

---

## Health Table Structure

### Schema

```sql
CREATE TABLE IF NOT EXISTS health (
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
```

### Invariants

1. **One Row Per Component:** Enforced by `PRIMARY KEY(component)`
2. **Ephemeral State:** Cleaned on app startup/shutdown via `clean_all()`
3. **Heartbeat Currency:** `last_heartbeat` updated every 5s by worker, checked every 10s by monitor
4. **Status Lifecycle:** Must follow valid transitions (see below)

### Status Lifecycle

```
starting → healthy ⟷ (periodic heartbeat updates)
             ↓
           stopping (graceful shutdown, exit_code=0)
             
starting → crashed → starting (auto-restart with backoff)
             ↓
           failed (restart limit exceeded, manual intervention required)
```

**Allowed Status Values:**

- `"starting"`: Process spawned, not yet in main loop
  - Written by: `BaseWorker.run()` on startup, `WorkerSystemService._restart_worker()`
  - Next: `"healthy"` (after first heartbeat)

- `"healthy"`: Running normally, heartbeat current
  - Written by: `BaseWorker._update_heartbeat()` every 5s
  - Next: `"stopping"` (graceful), `"crashed"` (unexpected death)

- `"stopping"`: Shutting down gracefully
  - Written by: `BaseWorker.run()` finally block, `Application.stop()`
  - Exit code: Usually 0 (clean shutdown)

- `"crashed"`: Died unexpectedly (non-zero exit or heartbeat timeout)
  - Written by: `WorkerSystemService._monitor_worker_health()`
  - Includes: `exit_code`, `metadata` with error details
  - Next: `"starting"` (auto-restart) or `"failed"` (limit exceeded)

- `"failed"`: Permanent failure, will not auto-restart
  - Written by: `WorkerSystemService._restart_worker()` (if restart limit exceeded)
  - Requires: Manual intervention via `reset_restart_count()`

### Key Operations

**Write Operations:**

| Method | Purpose | Fields Updated |
|--------|---------|----------------|
| `upsert_component()` | Low-level UPSERT | All fields (explicit control) |
| `update_heartbeat()` | Periodic heartbeat | `last_heartbeat`, `status`, `current_job` |
| `mark_starting()` | Process spawn | `status="starting"`, `pid`, `last_heartbeat` |
| `mark_healthy()` | Transition to healthy | `status="healthy"`, optional `pid` |
| `mark_stopping()` | Graceful shutdown | `status="stopping"`, `exit_code` |
| `mark_crashed()` | Unexpected death | `status="crashed"`, `exit_code`, `metadata` |
| `mark_failed()` | Permanent failure | `status="failed"`, `metadata` |
| `increment_restart_count()` | Increment on restart | `restart_count++`, `last_restart=now` |
| `reset_restart_count()` | Admin recovery | `restart_count=0`, `status="stopped"` |

**Read Operations:**

| Method | Purpose | Returns |
|--------|---------|---------|
| `get_component(component)` | Single health record | Dict with all fields or `None` |
| `get_all_workers()` | All worker records | List of dicts (excludes "app") |
| `get_app_health()` | App health record | Dict or `None` |
| `is_healthy(component, max_age_ms)` | Liveness check | Boolean (checks status + heartbeat age) |

**Cleanup Operations:**

| Method | Purpose |
|--------|---------|
| `clean_all()` | Delete all records (app startup/shutdown only) |
| `clean_worker_state()` | Delete worker records (emergency/testing) |

---

## State Broker and SSE

### StateBroker Overview

`StateBroker` maintains current system state and broadcasts updates via Server-Sent Events (SSE).

**Key Features:**
- **State Snapshot on Subscribe:** Clients receive full state on connection
- **Incremental Updates:** Subsequent events are delta updates
- **DB Polling:** Polls DB meta/health tables every 0.5s for worker updates (Phase 3.6 multiprocessing IPC)
- **Topic Wildcards:** Supports pattern matching (`worker:*:status`, `queue:tag:*`)

### DTO Types

**Defined in:** `nomarr.helpers.dto.events_state_dto`

```python
@dataclass
class QueueState:
    """Queue statistics (per-queue or global aggregate)."""
    queue_type: str | None  # None for global, "tag"/"library"/"calibration" for per-queue
    pending: int
    running: int
    completed: int
    avg_time: float
    eta: float

@dataclass
class JobState:
    """Individual job state."""
    id: int
    path: str | None
    status: str  # "pending", "running", "done", "error"
    error: str | None
    results: dict[str, Any] | None

@dataclass
class WorkerState:
    """Worker process state."""
    component: str  # Full component ID: "worker:{queue_type}:{id}"
    id: int | None  # Parsed numeric worker ID
    queue_type: str | None  # "tag", "library", "calibration"
    status: str  # "starting", "healthy", "stopping", "failed", "crashed"
    pid: int | None
    current_job: int | None

@dataclass
class SystemHealthState:
    """System health state."""
    status: str  # "healthy", "degraded", "error"
    errors: list[str]
```

### SSE Topics

**Queue Topics:**
- `queue:status` - Global aggregated queue statistics (all queues)
- `queue:{queue_type}:status` - Per-queue statistics (`tag`, `library`, `calibration`)
- `queue:*:status` - All per-queue statistics
- `queue:jobs` - All active jobs with current state

**Worker Topics:**
- `worker:{queue_type}:{id}:status` - Specific worker (e.g., `worker:tag:0:status`)
- `worker:{queue_type}:*:status` - All workers for queue type (e.g., `worker:tag:*:status`)
- `worker:*:status` - All workers (all queue types)

**System Topics:**
- `system:health` - System health and errors

### Event Broadcasting

**Subscription Flow:**
1. Client calls `subscribe(topics)` → receives `(client_id, event_queue)`
2. StateBroker sends state snapshot for each subscribed topic
3. StateBroker polls DB every 0.5s and broadcasts incremental updates
4. Client reads from `event_queue` (non-blocking)

**Event Format:**
```json
{
  "topic": "worker:tag:0:status",
  "type": "worker_update",
  "timestamp": 1733443200000,
  "worker": {
    "component": "worker:tag:0",
    "id": 0,
    "queue_type": "tag",
    "status": "healthy",
    "pid": 12345,
    "current_job": 42
  }
}
```

### DB Polling Mechanism (Phase 3.6)

**Problem:** Workers are separate processes, cannot call StateBroker methods directly.

**Solution:** Workers write state to DB tables, StateBroker polls and broadcasts.

**Polling Loop (`StateBroker._poll_worker_state()`):**
```python
while not self._shutdown:
    # Poll queue stats from meta table
    for queue_type in ["tag", "library", "calibration"]:
        stats_json = db.meta.get(f"queue:{queue_type}:stats")
        if stats_json:
            self.update_queue_state_for_type(queue_type, **json.loads(stats_json))
    
    # Poll worker health from health table
    workers = db.health.get_all_workers()
    for worker in workers:
        component = worker["component"]
        current_job_id = worker["current_job"]
        
        # Get job details from meta table
        if current_job_id:
            job_status = db.meta.get(f"job:{current_job_id}:status")
            job_path = db.meta.get(f"job:{current_job_id}:path")
            self.update_job_state(current_job_id, path=job_path, status=job_status)
        
        # Broadcast worker state
        self.update_worker_state(component, **worker_state)
    
    time.sleep(0.5)  # Poll interval
```

**Worker-Side Publishing (`BaseWorker`):**
```python
# Publish job state to meta table
db.meta.set(f"job:{job_id}:status", status)
db.meta.set(f"job:{job_id}:path", path)
db.meta.set(f"job:{job_id}:results", json.dumps(results))

# Publish queue stats to meta table
db.meta.set(f"queue:{queue_type}:stats", json.dumps(stats))
```

---

## Pause/Resume Behavior

### Global Worker Control

**Mechanism:** `worker_enabled` flag in DB meta table controls global worker system state.

**Default:** `True` (workers enabled on startup unless DB says otherwise)

### Pause Operation

**API:** `WorkerSystemService.pause_all_workers()` → `WorkerOperationResult`

**Process:**
1. Set DB meta: `worker_enabled=false`
2. Call `stop_all_workers()`:
   - Signal all workers to stop (set `_stop_event`)
   - Wait up to 10s for graceful shutdown
   - Terminate any workers still alive after timeout
   - Workers write `mark_stopping(component, exit_code=0)` on exit
3. Clear worker lists
4. Return success result

**Worker-Side Behavior:**
- Workers periodically check `db.meta.get("worker_enabled")` in `_is_paused()`
- If `"false"`, workers skip new job pickup but finish current job
- Main loop exits on next iteration after flag check

**Important:** Pause does NOT forcibly stop in-progress jobs. Workers finish current job, then idle.

### Resume Operation

**API:** `WorkerSystemService.resume_all_workers()` → `WorkerOperationResult`

**Process:**
1. Set DB meta: `worker_enabled=true`
2. Call `start_all_workers()`:
   - Check `is_worker_system_enabled()` → `True`
   - Spawn fresh worker processes for each queue type
   - Workers write `mark_starting()` on spawn
   - Health monitor starts checking heartbeats

**Restart Count Handling:**
- Restart counts are NOT reset on pause/resume
- Only reset via explicit admin operation: `reset_restart_count(component_id)`

---

## Restart Logic and Backoff

### Constants

```python
MAX_RESTARTS_IN_WINDOW = 5           # Max restarts before marking failed
RESTART_WINDOW_MS = 5 * 60 * 1000    # 5 minutes in milliseconds
MAX_BACKOFF_SECONDS = 60             # Max exponential backoff delay
HEARTBEAT_STALE_THRESHOLD_MS = 30000 # 30 seconds heartbeat timeout
HEALTH_CHECK_INTERVAL_SECONDS = 10   # Health monitor polling interval
```

### Restart Decision Logic

**Implemented in:** `WorkerSystemService._restart_worker()`

```python
# Step 1: Increment restart count atomically
restart_info = db.health.increment_restart_count(component_id)
restart_count = restart_info["restart_count"]
last_restart_ms = restart_info["last_restart"]

# Step 2: Check if restart limit exceeded
now_ms = int(time.time() * 1000)
time_since_last_restart = now_ms - last_restart_ms

if restart_count >= MAX_RESTARTS_IN_WINDOW and time_since_last_restart < RESTART_WINDOW_MS:
    # Too many restarts in short window → mark as permanently failed
    db.health.mark_failed(component, f"Failed after {restart_count} restart attempts")
    return  # Give up, do not restart

# Step 3: Apply exponential backoff
backoff_delay = min(2 ** restart_count, MAX_BACKOFF_SECONDS)
time.sleep(backoff_delay)

# Step 4: Stop old worker and start new one
worker.stop()
worker.join(timeout=5)
if worker.is_alive():
    worker.terminate()

new_worker = create_worker(queue_type, worker_id)
new_worker.start()
db.health.mark_starting(component, pid=new_worker.pid)
```

### Backoff Calculation

**Formula:** `backoff_seconds = min(2^restart_count, 60)`

| Restart Count | Backoff Delay |
|---------------|---------------|
| 1 | 2 seconds |
| 2 | 4 seconds |
| 3 | 8 seconds |
| 4 | 16 seconds |
| 5 | 32 seconds |
| 6+ | 60 seconds (capped) |

**Rationale:**
- Rapid restarts for transient failures (network blips, temporary resource exhaustion)
- Exponential increase prevents restart loops from overwhelming system
- Cap at 60s prevents excessive delays for recoverable issues

### Restart Window Semantics

**Definition:** 5-minute sliding window for restart count tracking.

**Behavior:**
- If worker restarts 5+ times within any 5-minute period → mark as `"failed"`
- Restart count persists indefinitely (not time-based decay)
- Only reset via manual admin operation

**Example Timeline:**
```
T=0:00 - Worker crashes (restart_count=1)
T=0:02 - Restart 1 (backoff=2s)
T=0:05 - Worker crashes (restart_count=2)
T=0:09 - Restart 2 (backoff=4s)
T=0:15 - Worker crashes (restart_count=3)
T=0:23 - Restart 3 (backoff=8s)
T=0:35 - Worker crashes (restart_count=4)
T=0:51 - Restart 4 (backoff=16s)
T=1:10 - Worker crashes (restart_count=5)
         Time since first restart: 70s < 5min
         Mark as "failed", stop restarting
```

### Manual Recovery

**API:** `WorkerSystemService.reset_restart_count(component_id)`

**Process:**
1. Call `db.health.reset_restart_count(component_id)`
2. Health record updated:
   ```python
   restart_count = 0
   last_restart = NULL
   status = "stopped"
   exit_code = NULL
   metadata = NULL
   ```
3. Worker can now be restarted without triggering failure threshold

**Note:** This does NOT automatically restart the worker. Admin must call resume or restart service.

---

## Exit Code Handling

### Exit Code Types

**Normal Exit Codes (Python Process):**
- `0`: Clean shutdown
- `1`: General error (unhandled exception)
- `2`: Command-line usage error (unlikely in worker context)
- `-N`: Killed by signal N (e.g., `-9` = SIGKILL, `-15` = SIGTERM)

**Nomarr-Specific Exit Codes:**
```python
EXIT_CODE_UNKNOWN_CRASH = -1       # Process died, exitcode unavailable
EXIT_CODE_HEARTBEAT_TIMEOUT = -2   # Stale heartbeat (>30s)
EXIT_CODE_INVALID_HEARTBEAT = -3   # Heartbeat timestamp is invalid type
```

### Exit Code Usage

**In Health Monitoring (`WorkerSystemService._monitor_worker_health()`):**

```python
# Case 1: Invalid heartbeat type
if not isinstance(last_heartbeat, int):
    db.health.mark_crashed(
        component=component_id,
        exit_code=EXIT_CODE_INVALID_HEARTBEAT,
        metadata="Invalid heartbeat timestamp"
    )
    restart_worker()

# Case 2: Stale heartbeat (>30s)
if heartbeat_age > HEARTBEAT_STALE_THRESHOLD_MS:
    db.health.mark_crashed(
        component=component_id,
        exit_code=EXIT_CODE_HEARTBEAT_TIMEOUT,
        metadata=f"Heartbeat stale for {heartbeat_age}ms"
    )
    restart_worker()

# Case 3: Process died
if not worker.is_alive():
    exit_code = worker.exitcode if worker.exitcode is not None else EXIT_CODE_UNKNOWN_CRASH
    db.health.mark_crashed(
        component=component_id,
        exit_code=exit_code,
        metadata=f"Process terminated unexpectedly with exit code {exit_code}"
    )
    restart_worker()
```

**In Health Table:**
- Exit code stored in `exit_code` column (INTEGER)
- Visible in health record queries: `get_component()`, `get_all_workers()`
- Used for crash diagnostics and admin reporting

### Crash Diagnostics

**Reading Exit Codes:**
```python
health = db.health.get_component("worker:tag:0")
if health["status"] == "crashed":
    exit_code = health["exit_code"]
    metadata = health["metadata"]
    
    if exit_code == EXIT_CODE_HEARTBEAT_TIMEOUT:
        # Worker hung, stopped sending heartbeats
    elif exit_code == EXIT_CODE_INVALID_HEARTBEAT:
        # DB corruption or worker bug
    elif exit_code == -9:
        # Killed by SIGKILL (OOM, manual kill)
    elif exit_code == 1:
        # Unhandled exception in worker
```

---

## IPC Architecture

### Why DB-Based IPC?

**Problem:** Workers are separate `multiprocessing.Process` instances:
- Cannot share Python objects (no shared memory)
- Cannot call StateBroker methods directly (different address space)
- Need cross-process communication mechanism

**Solution:** Database as shared state store:
- SQLite in WAL mode (concurrent read/write safe)
- Workers write state to DB tables (health, meta)
- StateBroker polls DB and broadcasts via SSE
- Simple, reliable, no message queues or sockets needed

### IPC Data Flow

```
┌─────────────────┐
│  Worker Process │
│   (tag:0)       │
└────────┬────────┘
         │ 1. Write heartbeat
         │    db.health.update_heartbeat()
         ├────────────────────────────────┐
         │                                 │
         │ 2. Write job state              │
         │    db.meta.set("job:42:status") │
         │                                 │
         ▼                                 ▼
┌──────────────────────────────────────────────┐
│           SQLite Database (WAL mode)         │
│  ┌────────────────┐  ┌───────────────────┐  │
│  │  health table  │  │   meta table      │  │
│  │   (workers)    │  │ (job state, stats)│  │
│  └────────────────┘  └───────────────────┘  │
└──────────────────────────────────────────────┘
         │                                 │
         │ 3. Poll every 0.5s              │
         │    db.health.get_all_workers()  │
         │    db.meta.get("job:*:*")       │
         │                                 │
         ▼                                 │
┌─────────────────┐                        │
│  StateBroker    │                        │
│  (main process) │◄───────────────────────┘
└────────┬────────┘
         │ 4. Broadcast via SSE
         │    client_queue.put(event)
         ▼
┌─────────────────┐
│   SSE Clients   │
│  (web, admin)   │
└─────────────────┘
```

### Key Tables for IPC

**Health Table (`health`):**
- Primary purpose: Worker heartbeat and lifecycle tracking
- Read by: WorkerSystemService (health monitor), StateBroker (SSE poll)
- Written by: Workers (heartbeat), WorkerSystemService (restart, crash)
- Fields used for IPC: `component`, `last_heartbeat`, `status`, `current_job`, `pid`

**Meta Table (`meta`):**
- Primary purpose: Key-value config store
- Repurposed for IPC: Job state, queue stats, worker events
- Read by: StateBroker (SSE poll), Workers (pause check)
- Written by: Workers (job/queue state), WorkerSystemService (global flags)
- Key patterns:
  - `worker_enabled`: Global pause/resume flag
  - `job:{id}:status`: Job lifecycle state
  - `job:{id}:path`: Job file path
  - `job:{id}:results`: Job processing results (JSON)
  - `job:{id}:error`: Job error message
  - `queue:{type}:stats`: Queue statistics (JSON)
  - `queue:{type}:last_update`: Stats freshness timestamp

### Concurrency Safety

**SQLite WAL Mode:**
- Multiple readers + single writer concurrency
- Workers write infrequently (every 5s heartbeat, per-job events)
- StateBroker polls frequently (every 0.5s) but read-only
- No lock contention in normal operation

**Transaction Boundaries:**
- All writes in `HealthOperations` and `MetaOperations` auto-commit
- Short transactions (single INSERT/UPDATE)
- No long-running transactions or nested writes

**Process Safety:**
- Each process creates own `sqlite3.Connection`
- No shared connection objects across processes
- Database file is shared (OS-level file locking via SQLite)

---

## Summary

**Worker Lifecycle:** spawn → heartbeat (5s) → graceful stop OR crash → auto-restart (with backoff) OR mark failed

**Health Table:** Single source of truth for worker liveness, restart counts, current jobs, exit codes

**StateBroker:** Polls DB (0.5s), maintains state DTOs, broadcasts SSE events to clients

**Pause/Resume:** Global flag in DB meta (`worker_enabled`), stops/starts all workers, preserves restart counts

**Restart Logic:** Exponential backoff (2^N seconds, max 60s), 5 restarts in 5min → permanent failure, manual reset required

**Exit Codes:** Track crash reasons (-1=unknown, -2=heartbeat timeout, -3=invalid heartbeat, others=process exit codes)

**IPC:** DB-based (health + meta tables), workers write state, StateBroker polls and broadcasts, no shared memory or sockets needed
