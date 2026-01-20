# Worker System Regression Checklist

**Context**: Discovery-based worker refactor (queue → discovery)  
**Status**: ✅ Core pipe-based health telemetry implemented (Steps 1-8 complete)

---

## Executive Summary

Discovery refactor preserved core functionality. Pipe-based health telemetry implemented - real-time health via pipe/FD; DB is history-only.

- **Core Features**: ✅ Preserved
- **Pipe Telemetry**: ✅ Implemented (Steps 1-8)
- **HealthMonitor**: ✅ Redesigned to pipe-based telemetry + status polling

---

## Pipe/FD Health Telemetry (Single Source of Truth)

Real-time health **MUST NOT** depend on Arango/DB. All liveness detection uses pipe/FD channels.

### Hard Constraints

- HealthMonitor runs in the main process; must remain generic + dumb
- Workers are spawned via `multiprocessing.Process` today; design must remain language-agnostic for future non-Python workers
- Real-time health signal is pipe/FD only; DB is write-only history
- Children must detect main-process death (channel close / write failure) and exit gracefully AFTER completing current job
- Owner reports only: `healthy` | `unhealthy` | `pending` | `failed`
- HealthMonitor may internally track "no recent frame" for detection, but `unknown` is NOT a callback return status

### Topology

```
Worker Process                    Main Process
┌───────────────────┐             ┌────────────────────────┐
│  Health Frame     │───pipe───→│  Owner (registry)      │
│  Writer Thread    │             │  in-memory status      │
└───────────────────┘             └──────────┬─────────────┘
                                           │
                                  get_status(component_id)
                                           │
                                           ▼
                                 ┌────────────────────────┐
                                 │  HealthMonitor         │
                                 │  (polls owner)         │
                                 └──────────┬─────────────┘
                                           │
                                  batched snapshot (async)
                                           │
                                           ▼
                                 ┌────────────────────────┐
                                 │  Health History        │
                                 │  Collection (DB)       │
                                 └────────────────────────┘
```

### Per-Worker Pipe Channel

- Parent creates a **dedicated pipe/FD per worker** at spawn time (not a shared single pipe)
- Worker writes periodic newline-delimited "health frames" to that channel:
  - Minimum: `component_id`, `status`
  - Optional: `current_job`, `phase`, telemetry fields (but not required for monitoring)
- Parent/owner reads frames, updates in-memory status registry keyed by `component_id`
- If worker writes fail (broken pipe) → main process died → worker finishes current job then exits

### Frame Format (Example)

```
HEALTH|{"component_id":"worker:tag:0","status":"healthy","job":"file123"}
```

- Prefix `HEALTH|` distinguishes from stdout/stderr noise
- JSON payload; owner parses and updates registry
- Frame interval: configurable (e.g., every 5s)

### Main Process Death Detection

- Worker must detect closed channel or write failure on next frame attempt
- On detection: log, finish current job, exit gracefully
- Do NOT exit mid-job; complete work first to avoid orphaned claims

---

## Health History Collection (Write-Only Snapshots)

DB health collection is for **history/diagnostics only**. NOT used for real-time health decisions.

### Requirements

- **Owned by HealthMonitor service**, not workers
- HealthMonitor periodically batches a snapshot of all current in-memory statuses into the collection
- Snapshot interval: configurable (e.g., every 30s)
- **Workers NEVER write health to DB** for monitoring purposes
- **HealthMonitor NEVER reads this collection** to make health decisions (write-only; not in critical path)
- Single source of truth is pipe telemetry; if pipe is wrong, fix pipe—don't maintain dual real-time paths
- Snapshot writes are best-effort, non-blocking; failures do not impact health decisions

### Purpose

- Historical audit trail of component health
- UI dashboards showing health over time
- Post-mortem diagnostics after failures
- NOT for liveness detection

---

## Health Monitoring Redesign (Required for Regression Fix)

HealthMonitor must be **purely domain-agnostic**. It polls owners for status (derived from pipe telemetry) and records results. All domain logic stays in the owning service. DB is history-only.

### Problem Statement

Current `HealthMonitorService` embeds domain knowledge:
- Calls `worker.start()` directly (component-specific)
- Reads DB to check heartbeat freshness (couples liveness to DB availability)
- Interprets metadata like `cache_loaded` to adjust thresholds
- Manages backoff/retry timing internally
- Holds Process/Thread references

**Fix**: HealthMonitor becomes a status poller. Real-time health comes from pipe telemetry. Owner interprets frames and provides status. DB is write-only history.

### Owner Status Contract

HealthMonitor understands exactly four statuses, reported by the component owner:

| Status | Meaning | HealthMonitor Behavior |
|--------|---------|------------------------|
| `pending` | Component not yet ready (initializing, loading models, cold start) | **No liveness evaluation**. Poll owner each interval until status changes. Do not declare dead. |
| `healthy` | Component running normally | Normal monitoring. Record healthy state. |
| `unhealthy` | Component alive but self-repairing (backoff, restart attempt, GPU recovery) | **Do not mark dead**. Continue polling. Surface "unhealthy" to callers querying status. |
| `failed` | Permanent failure; owner gave up | **Stop monitoring** this `component_id`. Record failure state. |

**Key rules**:
- HealthMonitor **polls owner** on each interval; owner returns current status
- HealthMonitor **never interprets reasons**—owner logs reasons internally
- HealthMonitor **never calls** `.start()`, `.terminate()`, or any Process/Thread methods
- HealthMonitor **never holds** Process/Thread references; tracks by `component_id` (string) only
- HealthMonitor **never reads DB** to determine liveness
- HealthMonitor **never blocks or sleeps** for backoff; only scheduling is "next periodic check"
- If owner has no recent frame from worker, owner may return `unhealthy` or trigger restart privately

### Responsibilities Split

#### HealthMonitor (Generic, Main Process)

- Register components by `component_id` with reference to owner
- On each check interval: call `owner.get_status(component_id)` → receive one of four statuses
- Record status in memory; if `failed`, stop monitoring that component
- Expose `get_component_status(component_id)` for other services to query
- Periodically batch-write in-memory statuses to Health History Collection (async, non-blocking)
- Never interpret domain metadata, never manage timers beyond periodic check, never read DB for decisions

#### Component Owner (e.g., WorkerSystemService, Main Process)

- Spawns worker processes, creates dedicated pipe/FD per worker
- Reads health frames from pipe, updates in-memory status registry
- Implements `get_status(component_id) -> Status` called by HealthMonitor
- Determines status from pipe telemetry:
  - Recent frame with phase="initializing" → `pending`
  - Recent frame with phase="processing"/"idle" → `healthy`
  - Recent frame with phase="backing_off" or internal recovery → `unhealthy`
  - No frames + restart attempts exhausted → `failed`
  - No frames + restart possible → `unhealthy` (while attempting restart)
- Owns Process lifecycle entirely; HealthMonitor never touches it
- Logs domain-specific reasons: "worker pending: TF model loading", "worker unhealthy: GPU backoff"

#### Worker/Component (e.g., DiscoveryWorker, Child Process)

- Writes health frames to dedicated pipe (background thread, non-blocking)
- Frame continues during long-running `process_file_workflow()` execution
- Reports: `component_id`, `status`, optional `phase`, `current_job`, telemetry
- Detects main-process death via write failure; finishes current job then exits
- Handles internal concerns: GPU preflight, cache eviction, error recovery
- Logs its own state transitions for observability

---

## Feature Comparison Matrix

### ✅ Core Features (Preserved)

| Feature | Old Implementation | New Implementation | Status |
|---------|-------------------|-------------------|--------|
| Health monitoring | `_heartbeat_loop()` thread writing to `health` table every 5s | Pipe-based frames to owner; DB is history-only | ✅ Redesigned |
| Database connection | Created in `run()` for process safety | Created in `run()` with explicit params | ✅ Preserved |
| Graceful shutdown | `_stop_event` + cleanup in finally | `_stop_event` + `mark_stopping()` | ✅ Preserved |
| Error tracking | Mark job errors in queue | Release claim + consecutive error counter | ✅ Preserved (improved) |
| Worker pause/resume | Check `db.meta.get("worker_enabled")` | `WorkerSystemService.is_worker_system_enabled()` | ✅ Preserved (service layer) |
| Job tracking | `_current_job_id` in health table | `current_job` in pipe frame | ✅ Preserved |
| PID tracking | Stored in health table | Stored in owner registry | ✅ Preserved |

### � Critical Regressions (Fixed)

| Feature | Old Implementation | New Status | Implementation |
|---------|-------------------|-----------|----------------|
| **Background health-frame writer** | Separate `threading.Thread` running `_heartbeat_loop()` | ✅ Implemented | `_health_writer_loop()` thread in `DiscoveryWorker` writes frames to pipe |
| **GPU preflight checks** | `_check_gpu_available()` reading cached `gpu:health` before each job | ✅ Implemented | `ml_is_available()` check at worker startup, emits `unhealthy` if fails |
| **Cache state tracking** | `_cache_loaded` flag for cold start phase detection | ✅ Implemented | Workers start with `pending` status, transition to `healthy` after init |
| **Idle cache eviction** | `_check_cache_eviction()` calling `ml_cache_comp.check_and_evict_idle_cache()` | ✅ Implemented | Staleness eviction in `WorkerSystemService.get_status()` (10s threshold) |

### 🟡 Important Regressions (Should Fix)

| Feature | Old Implementation | New Status | Impact | Priority |
|---------|-------------------|-----------|---------|----------|
| **Rolling avg processing time** | `_update_avg_time()` storing to `db.meta` | ❌ Not implemented | Loss of performance metrics for frontend/monitoring | 🟡 **P2** |
| **Event publishing (SSE)** | `_publish_job_state()`, `_publish_queue_stats()` to meta table | ❌ Not implemented | No real-time frontend updates (if StateBroker still exists) | 🟡 **P2** |
| **Job metadata cleanup** | `_cleanup_job_metadata()` removing stale meta keys | ❌ Not implemented | Meta table bloat if SSE system still active | 🟡 **P3** |

### 🟢 Removed by Design (Not Regressions)

| Feature | Reason for Removal |
|---------|-------------------|
| Queue polling (`_dequeue()`, `_mark_complete()`, etc.) | Discovery model queries `library_files` directly |
| Job cancellation (`cancel()` method) | Release claim = instant retry; no interactive cancellation needed |
| Queue statistics (`_queue_stats()`, `_get_active_jobs()`) | Replaced by `discover_next_file()` + claim count |

### ✨ New Features (Discovery-Specific)

| Feature | Implementation | Benefit |
|---------|---------------|----------|
| **Claim-based distribution** | `discover_and_claim_file()` → atomic file claiming via unique `_key` | Eliminates queue collection, simpler data model |
| **Automatic crash recovery** | Claims auto-expire when heartbeat stale → file rediscoverable | No explicit `requeue_crashed_job()` logic needed |
| **Consecutive error limit** | `MAX_CONSECUTIVE_ERRORS = 10` → shutdown after repeated failures | Prevents infinite crash loops on bad files |
| **Deterministic work order** | `SORT file._key` ensures consistent file processing order | Multi-worker fairness, no duplicate work |

---

## Restoration Roadmap

### Phase 1: Critical Infrastructure (P0) - **MUST DO BEFORE PRODUCTION**

#### 1.1 Background Health-Frame Writer

**Problem**: Current inline heartbeat blocks on long processing jobs. Worker becomes unobservable during long files. Owner cannot determine liveness.

**Goal**: Worker writes health frames to pipe continuously, even during long-running processing. Owner reads frames to maintain in-memory status.

**Requirements**:
- Dedicated background thread writes frames to pipe FD
- Thread runs independently of main processing loop
- Continues emitting frames during entire `process_file_workflow()` execution
- Frame includes: `component_id`, `status`, `phase`, optional `current_job`
- Thread lifecycle: start before main loop, signal shutdown and join in finally block
- If write fails (broken pipe): main process died; finish current job then exit

**Restoration Steps**:
1. Add `_shutdown` flag to `DiscoveryWorker.__init__()`
2. Add `_current_file_id: str | None` to track current work (thread-safe)
3. Add `_phase: str` to track current phase (thread-safe)
4. Receive pipe write-end FD from parent at spawn time
5. Create `_health_frame_thread: threading.Thread` in `run()` before main loop
6. Thread writes `HEALTH|{...}` frames at configured interval
7. Start thread before worker loop, signal shutdown and join in finally block
8. On write failure: set shutdown flag, let main loop complete current job, exit

**Acceptance Criteria**:
- Frames continue every N seconds during 60s+ file processing
- Owner reads frames and maintains accurate in-memory status
- Write failure triggers graceful exit after current job

---

#### 1.2 GPU Preflight Checks (Worker Admission Control)

**Problem**: Workers crash on GPU errors instead of gracefully failing jobs.

**Design**: Worker admission control. GPU state affects worker behavior; surfaces via owner status derived from pipe frames.
- GPU unavailable → worker skips job, backs off internally, continues emitting frames with phase="backing_off"
- Owner reads frames, sees backing_off phase → reports `unhealthy` to HealthMonitor
- HealthMonitor sees `unhealthy`, does NOT mark dead, continues polling
- Worker logs: "GPU unavailable, backing off 30s"

**Requirements**:
- Check GPU health (cached `gpu:health` in meta table) before each job
- On GPU unavailable: release claim, apply internal backoff, continue main loop
- Worker emits frames with phase="backing_off" during recovery
- Owner interprets phase and reports `unhealthy` during backoff, `healthy` when processing resumes

**Restoration Steps**:
1. Add `_check_gpu_available()` method to `DiscoveryWorker`
2. Read cached GPU health from `db.meta.get("gpu:health")`
3. Apply staleness check to detect outdated GPU probes
4. Call before `process_file_workflow()` in main loop
5. On GPU unavailable: log warning, release claim, set `_phase = "backing_off"`, sleep, continue loop
6. Reset `_phase` to "idle" or "processing" when ready

**Acceptance Criteria**:
- GPU unavailable: worker logs, releases claim, backs off internally, frames continue
- Owner reports `unhealthy` during backoff (from pipe frame phase)
- No crashes on GPU errors

---

#### 1.3 Cache State Tracking (Cold Start Handling)

**Problem**: First-job TF cold start may take 1-5+ minutes. Owner needs to distinguish cold start from crash.

**Design**: Owner reports `pending` until cache/models loaded; then `healthy`. HealthMonitor sees `pending` and does NOT evaluate liveness—just polls until status changes.
- Worker tracks `_cache_loaded: bool = False` internally
- Worker emits frames with phase="initializing" during cold start
- Owner reads frames, sees initializing phase → reports `pending` to HealthMonitor
- After first successful job: `_cache_loaded = True`, phase="idle"/"processing", owner reports `healthy`
- `cache_loaded` is internal telemetry/logging, NOT a HealthMonitor rule

**Requirements**:
- Worker tracks `_cache_loaded: bool = False` initially
- Frame includes phase: "initializing", "loading_models", "processing", "idle", "backing_off"
- After first successful `process_file_workflow()`, set `_cache_loaded = True`
- Owner interprets worker phase to determine status:
  - Phase "initializing" or "loading_models" → `pending`
  - Phase "processing" or "idle" → `healthy`
  - Phase "backing_off" → `unhealthy`

**Restoration Steps**:
1. Add `_cache_loaded: bool = False` to `DiscoveryWorker.__init__()`
2. Add `_phase: str = "initializing"` to track current phase
3. Include phase in health frame
4. Set `self._cache_loaded = True` after first successful file
5. Transition `_phase` to "processing"/"idle" after warmup complete

**Acceptance Criteria**:
- Cold start worker: owner reports `pending` from pipe frames (phase="initializing")
- After first job: owner reports `healthy` (phase="processing"/"idle")
- HealthMonitor never interprets `cache_loaded`—only sees status from owner

---

#### 1.4 Idle Cache Eviction (Worker/ML Responsibility)

**Problem**: ML models stay in VRAM indefinitely, blocking other GPU workloads.

**Design**: Worker/ML leaf behavior. Does not affect monitoring or pipe telemetry.
- Worker tracks its own idle time
- After idle threshold, worker calls `check_and_evict_idle_cache()`
- Worker remains `healthy` throughout; cache eviction is resource management
- Pipe frames continue with phase="idle"; owner still reports `healthy`

**Requirements**:
- Worker tracks `_last_work_time: float` (updated on job complete/start)
- During idle periods, check if idle duration exceeds threshold (e.g., 5 minutes)
- If idle > threshold, call `check_and_evict_idle_cache()`
- Frames continue during eviction check

**Restoration Steps**:
1. Add `_last_work_time: float` tracking in `DiscoveryWorker`
2. Update `_last_work_time` when file processing completes
3. In idle branch (no work found), check `now - _last_work_time`
4. If idle > threshold, call `check_and_evict_idle_cache()`
5. Make threshold configurable via `ProcessorConfig`

**Acceptance Criteria**:
- Worker idle 5+ minutes: ML models evicted, VRAM freed
- Eviction is worker-internal; owner still reports `healthy`
- Pipe frames unaffected by eviction

---

### Phase 2: Important Features (P1-P2)

#### 2.1 Rolling Average Processing Time

**Old Code** (`base.py:440-455`):
```python
def _update_avg_time(self, job_elapsed: float) -> None:
    """Update rolling average processing time."""
    current_avg_str = self.db.meta.get("avg_processing_time")
    current_avg = float(current_avg_str) if current_avg_str else job_elapsed
    new_avg = (current_avg * 0.8) + (job_elapsed * 0.2)
    self.db.meta.set("avg_processing_time", str(new_avg))
```

**Restoration Steps**:
1. Add after successful `process_file_workflow()` call
2. Store as `avg_processing_time` in meta table
3. Consider: per-worker tracking (`avg_processing_time:worker:tag:0`)
4. Frontend can read for ETA calculations

**Benefit**: Restores performance metrics for monitoring/frontend

---

#### 2.2 Event Publishing (SSE)

**Investigation Needed**: Does StateBroker still exist? Does frontend need real-time updates?

**Old Code** (`base.py:457-496`):
```python
def _publish_job_state(self, job_id, path, status, results=None, error=None):
    """Publish job state to DB meta table (StateBroker polls)."""
    self.db.meta.set(f"job:{job_id}:status", status)
    self.db.meta.set(f"job:{job_id}:path", path)
    if results:
        self.db.meta.set(f"job:{job_id}:results", json.dumps(results))
    if error:
        self.db.meta.set(f"job:{job_id}:error", error)

def _publish_queue_stats(self):
    """Publish queue statistics."""
    stats = self._queue_stats()
    self.db.meta.set(f"queue:{self.queue_type}:stats", json.dumps(stats))
```

**Restoration Strategy**:
1. **If StateBroker exists**: Adapt to discovery model
   - Publish: `file:{file_id}:status`, `file:{file_id}:worker`
   - Replace queue stats with: `library_files.needs_tagging` count
2. **If StateBroker removed**: Skip (not needed)

**Action**: Check for `StateBroker` or `SSEBroker` in codebase

---

### Phase 3: Monitoring & Improvements (P3)

#### 3.1 Enhanced Discovery Metrics

**New Metrics to Add**:
- `discovery_attempts`: How many discover queries before finding work
- `claim_conflicts`: How many times another worker beat us to a file
- `files_processed`: Per-worker completion count (already tracked)
- `consecutive_errors`: Already tracked, but not exposed

**Implementation**:
```python
# In worker loop
self.metrics = {
    "discovery_attempts": 0,
    "claim_conflicts": 0,
    "files_processed": 0,
    "consecutive_errors": 0,
}

# Update heartbeat with metrics
db.health.update_heartbeat(
    self.worker_id,
    status="running",
    metadata=json.dumps({
        "cache_loaded": self._cache_loaded,
        "metrics": self.metrics,
    })
)
```

**Benefit**: Better observability into discovery efficiency

---

#### 3.2 Adaptive Polling Strategy

**Current**: Fixed `IDLE_SLEEP_S = 1.0` when no work found

**Improvement**: Exponential backoff when queue empty
```python
# Add to DiscoveryWorker
self._idle_backoff = 1.0  # Start at 1s
MAX_BACKOFF = 30.0  # Max 30s

# In main loop
if file_id is None:
    time.sleep(self._idle_backoff)
    self._idle_backoff = min(self._idle_backoff * 1.5, MAX_BACKOFF)
else:
    self._idle_backoff = 1.0  # Reset on work found
```

**Benefit**: Reduce DB load when no files need processing

---

#### 3.3 Graceful Error Recovery

**Current**: `MAX_CONSECUTIVE_ERRORS = 10` → shutdown

**Improvement**: Categorize errors, only count fatal ones
```python
# Fatal errors (count toward limit)
- GPU errors
- Database connection failures
- Out of memory

# Non-fatal errors (log but don't count)
- File not found (already deleted)
- Invalid audio format (expected for some files)
- Tag write failures (file permissions)
```

**Benefit**: Workers don't die from expected edge cases

---

#### 3.4 Claim Timeout Configuration

**Current**: `DEFAULT_HEARTBEAT_TIMEOUT_MS = 30_000` (hardcoded in `WorkerSystemService`)

**Improvement**: Make configurable via `ProcessorConfig`
```python
@dataclass
class ProcessorConfig:
    # ... existing fields ...
    claim_timeout_ms: int = 30_000  # Claim expires after worker heartbeat stale
```

**Benefit**: Adjust for slow files (e.g., long analysis tracks)

---

## Testing Strategy

### HealthMonitor Acceptance Criteria

1. **Real-time health is pipe-only; DB is history-only**
   - HealthMonitor never reads DB to determine liveness
   - Owner provides status derived from pipe frames
   - HealthMonitor writes to Health History Collection (batched, non-blocking, best-effort)

2. **No domain knowledge**
   - Monitor does not interpret `cache_loaded`, GPU state, backoff timers, phases, or any metadata
   - Monitor does not call `.start()`, `.terminate()`, or any Process/Thread methods
   - Monitor does not hold Process/Thread references; tracks by `component_id` only

3. **Pure status polling**
   - Monitor calls `owner.get_status(component_id)` on each interval
   - Returns one of: `pending`, `healthy`, `unhealthy`, `failed`
   - Monitor records status, does not interpret reasons

4. **Status-specific behavior**
   - `pending`: No liveness evaluation; poll until status changes; do not declare dead
   - `healthy`: Normal monitoring; record healthy state
   - `unhealthy`: Do NOT mark dead; continue polling; surface "unhealthy" to callers
   - `failed`: Stop monitoring; record failure state

5. **Health History writes are non-blocking**
   - Snapshot writes are async/batched; failures do not impact health decisions
   - Single source of truth is pipe telemetry; DB is audit trail only

6. **Main process death → workers exit after current job**
   - Worker detects closed pipe / write failure
   - Worker finishes current job, then exits gracefully

### Unit Tests Needed

1. **Health-Frame Writer Test**
   - Start worker, verify frames continue during 60s+ simulated job
   - Kill worker mid-job, verify cleanup runs (thread joins, pipe closed)
   - Verify frames use dedicated pipe, not stdout

2. **GPU Preflight Test**
   - Mock `gpu:health` unavailable → claim released, phase="backing_off" in frames
   - Owner reports `unhealthy` during backoff, `healthy` after recovery
   - Frames continue throughout

3. **Cold Start Status Test**
   - Worker starts, emits frames with phase="initializing"
   - Owner returns `pending` to HealthMonitor
   - After first job: phase changes, owner returns `healthy`
   - HealthMonitor never evaluates liveness during `pending`

4. **Idle Cache Eviction Test**
   - Worker idle 5+ min → `check_and_evict_idle_cache()` called
   - Frames continue with phase="idle"; owner reports `healthy`

5. **HealthMonitor Status Polling Test**
   - Register component, owner returns `pending` → monitor records pending, no death logic
   - Owner returns `unhealthy` → monitor records unhealthy, does not mark dead
   - Owner returns `healthy` → monitor records healthy
   - Owner returns `failed` → monitor stops polling, records failure

6. **Main Death Detection Test**
   - Close pipe from parent side mid-job
   - Worker detects write failure on next frame
   - Worker completes current job, then exits

### Integration Tests Needed

1. **Long Job (No False Death)**
   - Process 60s file with background health-frame writer
   - Frames continue throughout; owner reports `healthy`
   - HealthMonitor sees `healthy` on each poll

2. **Cold Start Transition** (pending → healthy)
   - Cold start worker, first job takes 120s (TF loading + processing)
   - Owner returns `pending` for N checks (from pipe frames with phase="initializing")
   - After job completes: owner returns `healthy`
   - HealthMonitor never declares death during pending phase

3. **Self-Repair Transition** (healthy → unhealthy → healthy)
   - Worker encounters GPU error, enters backoff
   - Frames have phase="backing_off"; owner returns `unhealthy`
   - HealthMonitor continues polling, does NOT mark dead
   - Worker recovers, owner returns `healthy`

4. **Main Death → Worker Exit**
   - Worker processing file, parent closes pipe
   - Worker detects on next frame write
   - Worker finishes current file, exits gracefully
   - Claim eventually expires; file rediscoverable

5. **Real Crash (No Frames)**
   - Worker crashes (simulate OOM)
   - Owner detects no recent frames, attempts restart, returns `unhealthy`
   - Max restarts exceeded: owner returns `failed`
   - HealthMonitor stops monitoring, records failure

---

## Risk Assessment

### High Risk

1. **HealthMonitor reads DB for liveness** → Redesign to pipe-telemetry + status polling (P0)
2. **Worker unobservable during long jobs** → Background health-frame writer (P0)
3. **Crashes on GPU errors** → GPU preflight with internal backoff (P0)
4. **False death during cold start** → Owner returns `pending` until ready (P0)

### Medium Risk

5. **VRAM leaks from idle models** → Idle cache eviction (P1)
6. **Missing performance metrics** → Rolling average (P2)

### Low Risk

7. **No real-time frontend updates** → Investigate StateBroker (P3)

---

## Success Criteria

**Phase 1 Complete** (January 2026):
- ✅ Real-time health via pipe telemetry only; DB is write-only history
- ✅ HealthMonitor redesigned: pure status polling, no domain logic, no DB reads
- ✅ Workers have background health-frame writer (pipe-based)
- ✅ Workers process 60s+ files while remaining observable via frames
- ✅ Workers handle GPU errors gracefully (owner reports `unhealthy`)
- ✅ Cold start workers: owner reports `pending` until ready
- ⬜ Main process death: workers detect and exit after current job (requires testing)
- ⬜ Idle workers free VRAM after 5+ minutes (ML cache eviction - future enhancement)

**Implementation Details**:
- `ComponentStatus` type: `Literal["pending", "healthy", "unhealthy", "failed"]`
- `ComponentOwner` protocol: `get_status(component_id)`, `get_component_ids()`
- Frame format: `HEALTH|{"component_id":"...","status":"..."}` (newline-delimited)
- Frame interval: 5 seconds (`HEALTH_FRAME_INTERVAL_S`)
- Staleness threshold: 10 seconds (`STATUS_STALE_THRESHOLD_S`)
- DB heartbeat removed from worker hot path
- Per-worker pipe: `Pipe(duplex=False)` for one-way child→parent telemetry
- Unit tests: 15 tests covering frame parsing, status registry, staleness eviction

**Phase 2 Complete**:
- ✅ Performance metrics visible
- ✅ SSE updates working or removed

**Phase 3 Complete**:
- ✅ Discovery metrics exposed
- ✅ Adaptive polling reduces DB load
- ✅ Error categorization prevents spurious shutdowns

---

## Open Questions

1. **StateBroker/SSE**: Does it still exist? Check for `StateBroker`, `SSEBroker`, `/events` endpoint
2. **TF cold start time**: Measure to validate pending duration (estimate: 1-5 minutes)
3. **Frame interval**: How often should workers emit frames? (5s default?)
4. **Health History snapshot interval**: How often should HealthMonitor batch-write to DB? (30s default?)

---

## References

- `git show 7cf4b73:nomarr/services/infrastructure/workers/base.py` (old queue worker)
- `docs/dev/DISCOVERY_WORKER_REFACTOR.md`
- `nomarr/services/infrastructure/workers/discovery_worker.py`
- `nomarr/services/infrastructure/worker_system_svc.py`
- `nomarr/persistence/database/worker_claims_aql.py`
- `nomarr/services/infrastructure/health_monitor_svc.py`
- `nomarr/components/workers/worker_crash_comp.py`
