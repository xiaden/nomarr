# Worker Restart/Backoff Regression Repair Plan

**Date:** January 21, 2026  
**Context:** Post queue→discovery refactor analysis  
**Status:** Analysis complete, implementation pending

---

## Executive Summary

After the queue→discovery refactor, **worker restart and backoff logic was never integrated**. The component (`worker_crash_comp.py`) exists and is correct, but `WorkerSystemService.on_status_change()` contains only a TODO comment. When workers crash, they are never restarted.

**Classification:** `worker_crash_comp.py` is **orphaned intent (Category B)** - responsibility missing, code never integrated.

**Solution:** This is primarily an **attachment/wiring task** - the restart decision logic (`worker_crash_comp.py`) is complete and correct, just never wired into the service. Only missing piece is persistence for restart counters. Implementation is:

1. **Attach:** Wire existing `should_restart_worker()` into `on_status_change()` callback (replace TODO)
2. **Persist:** Add new collection/operations for restart state (survives app restarts)
3. **Cleanup:** Align timer scheduling with architectural invariants (idempotent, shutdown-safe)

**Effort:** Low - no new domain logic needed, mostly connecting existing components.

---

## Non-goals / Prohibitions (Architectural Invariants)

**HealthMonitor is the sole authority for health state transitions.**

1. **No health decisions from DB:** WorkerSystemService must NOT read `last_heartbeat`, `probe_time`, or other staleness indicators from DB to decide if a worker is dead.
2. **No recomputed health:** Restart logic is triggered ONLY by HealthMonitor callbacks (`on_status_change` with `new_status="dead"`).
3. **DB is logging/API mirror only:** Health collection (if used for restart state) stores restart policy counters for persistence across app restarts, but must NOT be used for staleness computation.
4. **Separate concerns:** Restart policy state (restart_count, last_restart_wall_ms) is conceptually distinct from health telemetry (last_heartbeat, status). These MUST be stored in separate collections or clearly prefixed to prevent drift.
5. **Idempotent scheduling:** Only one pending restart timer per component_id. Double-scheduling is prohibited.

**These rules prevent the "DB-as-authority" antipattern where services read DB timestamps to recompute health instead of trusting HealthMonitor.**

---

## Current Behavior (Traced Code Paths)

### 1. Worker Spawning & Registration

**Service:** `WorkerSystemService.start_all_workers()` ([worker_system_svc.py:336-380](../nomarr/services/infrastructure/worker_system_svc.py#L336-L380))

- Creates `DiscoveryWorker` processes via `create_discovery_worker()` factory
- Creates pipe pair for health telemetry
- Registers each worker with `HealthMonitorService` via `register_component()`, passing:
  - `component_id` (e.g., `"worker:tag:0"`)
  - `handler=self` (WorkerSystemService implements `ComponentLifecycleHandler`)
  - `pipe_conn=parent_conn` (read-end)
  - `policy=DEFAULT_WORKER_POLICY` (60s startup, 5s staleness interval, 3 misses → dead)

### 2. Health Monitoring Lifecycle

**HealthMonitor:** `_monitor_loop()` ([health_monitor_svc.py:300-340](../nomarr/services/infrastructure/health_monitor_svc.py#L300-L340))

- Polls pipes using `multiprocessing.connection.wait()`
- On pipe EOF → calls `_handle_pipe_closed()` → transitions to **"dead"**
- On staleness (3 consecutive missed 5s heartbeats → 15s total) → transitions to **"dead"**
- On startup timeout (60s) → transitions to **"dead"**

**Worker:** `DiscoveryWorker` ([discovery_worker.py](../nomarr/services/infrastructure/workers/discovery_worker.py))

- Sends health frames every 5s via background thread (`_health_writer_loop`)
- On clean shutdown: closes pipe (EOF to parent)
- On crash: pipe breaks (EOF to parent)
- On consecutive errors (10+): self-terminates

### 3. Callback Handling (Dead Transitions)

**Callback:** `WorkerSystemService.on_status_change()` ([worker_system_svc.py:215-248](../nomarr/services/infrastructure/worker_system_svc.py#L215-L248))

```python
if new_status == "dead":
    logger.warning("[WorkerSystemService] Worker %s is dead, may need restart", component_id)
    # TODO: Implement restart logic with backoff if needed
```

**Current behavior: LOGS ONLY. No restart, no backoff, no failure marking.**

- Worker process remains dead, is **never restarted**
- No restart count tracking
- No backoff computation
- No permanent failure marking

### Current Regression: What Happens Today

**When a worker crashes or exits:**

1. HealthMonitor detects pipe EOF or missed heartbeats → transitions to "dead"
2. HealthMonitor calls `WorkerSystemService.on_status_change()`
3. WorkerSystemService logs a warning
4. **Worker is never restarted** (TODO comment present)
5. Worker count decreases permanently
6. No further action until manual intervention or app restart

**No backoff, no retry limit, no persistence of restart state.**

---

## Evaluation of worker_crash_comp.py

### Classification: B) Orphaned Intent

**Responsibility missing, code never integrated**

### Evidence

1. **Exported but never imported outside package:**
   - Exported from `nomarr/components/workers/__init__.py`
   - No imports found in `WorkerSystemService` or anywhere else in services/workflows
   - Only exists in package boundary, never called

2. **Responsibility analysis:**
   - `should_restart_worker()`: Takes `restart_count`, `last_restart_ms` → returns `RestartDecision` with action ("restart"/"mark_failed") + backoff
   - `calculate_backoff()`: Computes exponential backoff (1s → 60s cap)
   - Constants: `MAX_RESTARTS_IN_WINDOW=5`, `RESTART_WINDOW_MS=5min`, `MAX_LIFETIME_RESTARTS=20`
   - **This is exactly the missing logic from WorkerSystemService.on_status_change()**

3. **Design intent confirmed:**
   - Module docstring: "WorkerSystemService delegates restart decisions to this component"
   - Function is pure (no side effects except logging)
   - Matches architecture: components contain domain logic, services orchestrate
   - Matches docs: [workers.md](workers.md#L115-L130) describes exact same policy

4. **Persistence never implemented:**
   - No `restart_count` field in health collection
   - No `last_restart_ms` field in health collection
   - `health_aql.py` has no restart tracking functions
   - Worker death leaves no persistent state

### Conclusion

`worker_crash_comp.py` is **complete, correct, and ready to use**, but was never integrated into `WorkerSystemService`. The TODO in `on_status_change()` was never resolved.

**This is not a rebuild - it's a wiring job.** All restart decision logic exists and is architecturally sound. Only missing pieces:
1. Import statement in service
2. Persistence layer for restart counters (new collection)
3. Timer scheduling in callback (replacing TODO)
4. Shutdown-safe timer cleanup

---

## Comparison Against Desired Architecture

| Requirement | Current State | Desired State |
|-------------|---------------|---------------|
| Domain spawner decides restarts | ❌ No decision logic | ✅ WorkerSystemService calls worker_crash_comp |
| Backoff on restart | ❌ No restarts | ✅ Exponential backoff (1-60s) |
| Restart limits | ❌ No tracking | ✅ 5 in 5min, 20 lifetime |
| Permanent failure marking | ❌ No failure state | ✅ Calls HealthMonitor.set_failed() |
| State persistence | ❌ No fields | ✅ restart_count, last_restart_wall_ms in worker_restart_policy |
| HealthMonitor = fact reporter | ✅ Correct | ✅ Maintains |
| Worker = no self-restart | ✅ Correct | ✅ Maintains |

---

## Regression Repair Plan

### Ownership

**Restart/backoff policy lives in:**

- **Component:** `nomarr/components/workers/worker_crash_comp.py` ✅ **ALREADY EXISTS, NO CHANGES**
  - Contains pure decision logic (complete and tested via doctests)
  - `should_restart_worker()`, `calculate_backoff()`, `RestartDecision` dataclass
  - Constants: `MAX_RESTARTS_IN_WINDOW=5`, `RESTART_WINDOW_MS=5min`, `MAX_LIFETIME_RESTARTS=20`
  
- **Service:** `nomarr/services/infrastructure/worker_system_svc.py` ⚠️ **WIRE EXISTING COMPONENT**
  - Already owns worker process spawning/termination ✅
  - Already tracks worker process handles ✅
  - Already receives HealthMonitor callbacks ✅
  - **TODO remaining:** Call `should_restart_worker()` component (one function call)
  - **TODO remaining:** Implement restart scheduling with Timer
  - **TODO remaining:** Call `HealthMonitor.set_failed()` when appropriate
  
- **Persistence:** `nomarr/persistence/database/worker_restart_policy_aql.py` ⚠️ **NEW FILE NEEDED**
  - Separate collection/operations for restart policy state
  - Keeps health telemetry (health_aql.py) pure
  - Only truly new code required

**Layering respected:**

- `worker_crash_comp` (component) has no upward imports ✓
- `WorkerSystemService` (service) imports component ✓
- `HealthOperations` (persistence) has no business logic ✓

---

### State/Persistence

**Restart counts MUST survive process restarts** (service restarts, app crashes).

**Why:** Without persistence:

- App restart → all workers re-spawn at restart_count=0
- Rapid crash loop → app restart → loop continues indefinitely
- Defeats entire purpose of restart limits

**Separate collection for restart policy state (preferred design):**

**Collection:** `worker_restart_policy` (new)

```python
{
  "_key": "worker:tag:0",                       # component_id as document key
  "component_id": "worker:tag:0",               # redundant but queryable
  "restart_count": 3,                           # incremented on each restart
  "last_restart_wall_ms": 1737499900000,        # wall-clock timestamp (now_ms())
  "failed_at_wall_ms": null,                    # wall-clock timestamp when marked failed
  "failure_reason": null,                       # human-readable reason for permanent failure
  "updated_at_wall_ms": 1737499900000           # last write timestamp
}
```

**Why separate collection:**

- Prevents confusion between health telemetry (last_heartbeat, status) and restart policy (restart_count)
- Enforces architectural invariant: health decisions come from HealthMonitor callbacks, not DB queries
- Allows health collection to remain purely telemetry/logging (no policy state mixed in)

**Timestamp semantics:**

- `last_restart_wall_ms`, `failed_at_wall_ms`, `updated_at_wall_ms`: wall-clock milliseconds (`now_ms()` from helpers)
- Monotonic timestamps (HealthMonitor deadlines, staleness windows) remain in-memory only
- Wall-clock used here because restart windows ("5 in 5min") span app restarts and need absolute time

**New persistence methods (worker_restart_policy_aql.py, new file):**

```python
def get_restart_state(component_id: str) -> tuple[int, int | None]:
    """Get (restart_count, last_restart_wall_ms) for a component.
    Returns (0, None) if no record exists.
    """

def increment_restart_count(component_id: str) -> None:
    """Increment restart_count and set last_restart_wall_ms=now_ms().
    Uses UPSERT to create record if missing.
    """

def reset_restart_count(component_id: str) -> None:
    """Reset restart_count=0, last_restart_wall_ms=null.
    Used for manual admin reset (future feature).
    """

def mark_failed_permanent(component_id: str, failure_reason: str) -> None:
    """Set failed_at_wall_ms=now_ms(), record failure_reason.
    Does NOT modify restart_count (preserves history).
    """

def remove_restart_state(component_id: str) -> None:
    """Remove restart state entirely (clean slate).
    Used when worker is permanently removed.
    """
```

**No migration shim** (pre-alpha policy): New collection created on first write. Missing docs implicitly have `restart_count=0`.

---

### Policy (Explicit Rules)

**Restart threshold / max restarts:**

- Short window: 5 restarts in 5 minutes → mark_failed
- Long window: 20 total restarts → mark_failed
- (Constants already defined in `worker_crash_comp.py`)

**Backoff schedule:**

- Exponential: `2^restart_count` seconds, capped at 60s
- Sequence: 1s, 2s, 4s, 8s, 16s, 32s, 60s, 60s, ...
- (`calculate_backoff()` already implemented)

**Transitions to "failed":**

- When `should_restart_worker()` returns `action="mark_failed"`
- WorkerSystemService calls `HealthMonitor.set_failed(component_id)` (marks permanently failed in-memory)
- WorkerSystemService calls `db.worker_restart_policy.mark_failed_permanent(component_id, failure_reason)` (persists reason)
- No further callbacks for this component_id

**Idempotent restart scheduling:**

- WorkerSystemService tracks pending restart timers per component_id (in-memory dict/set)
- Before scheduling new timer, cancel any existing timer for that component_id
- Prevents double-scheduling if multiple "dead" transitions occur (should not happen, but defensive)
- Restart decisions triggered ONLY by `new_status=="dead"` callbacks from HealthMonitor
- **Timer cleanup on shutdown:** `stop_all_workers()` MUST cancel all pending timers before terminating workers

**Handling "recovering" windows:**

- Already supported by HealthMonitor contract
- Worker sends `{"status": "recovering", "recover_for_s": 30}` when resource-exhausted
- HealthMonitor clamps to [5s, 120s] per policy
- If recovery succeeds → worker sends `{"status": "healthy"}` → resets misses
- If recovery fails → transition to "dead" → restart logic applies
- **No special handling needed in restart logic** (recovering → dead follows same path)

**Handling "normal/finished exit":**

- **Current gap:** No distinction between crash and graceful shutdown
- **Analysis:** Workers are designed to run indefinitely (discovery loop). Normal exit scenarios:
  1. Explicit stop via `WorkerSystemService.stop_all_workers()` → sets `_stop_event`
  2. Consecutive errors (10+) → self-terminates
  3. Preflight failure (Essentia unavailable) → exits after 10s

- **Proposed solution:** Do NOT add "finished" status (violates pre-alpha simplicity rule)
- **Implementation:** Track whether stop was requested:
  ```python
  def on_status_change(...):
      if new_status == "dead":
          if self._stop_event.is_set():
              # Graceful shutdown requested - do not restart
              logger.info("Worker stopped gracefully, not restarting")
              return
          # Unexpected death - apply restart logic
  ```

---

### Scope of Change

**Files to modify:**

1. **nomarr/persistence/database/worker_restart_policy_aql.py** (new file)
   - Create `WorkerRestartPolicyOperations` class
   - `get_restart_state()`
   - `increment_restart_count()`
   - `reset_restart_count()`
   - `mark_failed_permanent()`
   - `remove_restart_state()`

2. **nomarr/persistence/db.py** (wire new operations)
   - Add `self.worker_restart_policy = WorkerRestartPolicyOperations(db)` to Database class

3. **nomarr/services/infrastructure/worker_system_svc.py** (replace TODO)
   - Import `should_restart_worker`, `RestartDecision` from `nomarr.components.workers`
   - Add `_pending_restart_timers: dict[str, threading.Timer]` instance variable
   - Replace `on_status_change()` TODO with restart logic
   - Add private method `_restart_worker(component_id: str)` to spawn replacement worker
   - Modify `stop_all_workers()` to cancel all pending restart timers before worker termination

3. **nomarr/components/workers/worker_crash_comp.py** (no changes)
   - Already complete and correct

**Files to test:**

1. **tests/unit/services/test_worker_system_svc.py** (new tests)
   - Test restart decision on "dead" callback
   - Test backoff scheduling
   - Test failure marking after limits exceeded
   - Mock `should_restart_worker()`, verify calls

2. **tests/unit/persistence/test_worker_restart_policy_aql.py** (new test file)
   - Test restart_count increment/reset
   - Test restart state retrieval
   - Test failure reason persistence
   - Test UPSERT behavior (missing docs)

**No deletion needed** - `worker_crash_comp.py` is sound.

---

### Deletion vs Integration Policy

**Decision: INTEGRATION (not deletion)**

**This is attachment work, not a rewrite.** The component exists and is correct - we're just connecting it.

**Integration plan:**

1. **Phase 1: Persistence** (blocking, ~30 min)
   - Create `worker_restart_policy_aql.py` with 5 methods (~100 lines)
   - Wire into `db.py` as `self.worker_restart_policy` (1 line)
   - Add unit tests for persistence layer
   - No behavioral change yet

2. **Phase 2: Service integration** (main fix, ~45 min)
   - Import existing component in `worker_system_svc.py` (1 line)
   - Replace TODO with restart logic (~30 lines, mostly provided above)
   - Add `_restart_worker()` helper method (~40 lines, mostly copy from start_all_workers)
   - Modify `stop_all_workers()` timer cleanup (~5 lines)
   - Add unit tests mocking component

3. **Phase 3: End-to-end validation** (optional but recommended, ~15 min)
   - Integration test: kill worker → verify restart with backoff
   - Integration test: rapid crashes → verify permanent failure
   - Integration test: stop_all_workers → verify no restarts

**Total effort estimate: ~90 minutes** (plus testing time)

**No transitional state** - either restart is implemented or it isn't. No deprecated paths.

---

## Implementation Guide (Copilot-Ready)

**Implementation Nature:** This is primarily an **attachment task** - connecting existing, working components.

**What's already done:**
- ✅ Restart decision logic (`worker_crash_comp.py`) - complete, tested, correct
- ✅ Service scaffolding (`WorkerSystemService`) - handles callbacks, tracks workers
- ✅ Health monitoring (`HealthMonitorService`) - emits "dead" callbacks
- ✅ Worker spawning logic (`start_all_workers()`) - can be reused for restart

**What needs to be added:**
- ⚠️ Persistence for restart counters (new collection + 5 methods)
- ⚠️ Wire component into callback (import + call `should_restart_worker()`)
- ⚠️ Timer scheduling in `on_status_change()` (replace TODO)
- ⚠️ Timer cleanup in `stop_all_workers()` (cancel pending restarts)

**Estimated LOC:** ~175 lines (100 persistence, 75 service changes)

---

### Constraints (MUST follow)

1. Do NOT modify `worker_crash_comp.py` - it is complete and correct
2. Do NOT rename `_id`, `_key`, `component_id` fields (ArangoDB-native naming)
3. Do NOT create migrations, backward-compat layers, or deprecation shims (pre-alpha)
4. Follow layering: services → components → persistence (no upward imports)
5. Use `restart_count` and `last_restart_wall_ms` field names (wall-clock timestamps)
6. Use `threading.Timer()` for backoff scheduling (not `time.sleep()` in callback)
7. Distinguish graceful shutdown (`_stop_event.is_set()`) from crashes (no "finished" status)
8. Implement idempotent restart scheduling (track pending timers, prevent double-schedule)
9. DB reads ONLY for restart policy counters, NEVER for health/staleness decisions

### Step 1: Add restart tracking to persistence (worker_restart_policy_aql.py)

**Create new file:** `nomarr/persistence/database/worker_restart_policy_aql.py`

Add method: `get_restart_state(component_id: str) -> tuple[int, int | None]`

- Query worker_restart_policy collection for `restart_count`, `last_restart_wall_ms`
- Return (0, None) if document missing

Add method: `increment_restart_count(component_id: str) -> None`

- Use UPSERT to increment `restart_count`, set `last_restart_wall_ms=now_ms()`, `updated_at_wall_ms=now_ms()`
- Creates document if missing (restart_count=1)

Add method: `reset_restart_count(component_id: str) -> None`

- Set `restart_count=0`, `last_restart_wall_ms=null`, `updated_at_wall_ms=now_ms()`
- Used for manual admin reset (future feature)

Add method: `mark_failed_permanent(component_id: str, failure_reason: str) -> None`

- Set `failed_at_wall_ms=now_ms()`, record `failure_reason`, `updated_at_wall_ms=now_ms()`
- Does NOT modify restart_count (preserves history)

Add method: `remove_restart_state(component_id: str) -> None`

- Remove document from collection
- Used when worker is permanently removed

**Wire into db.py:**

```python
from nomarr.persistence.database.worker_restart_policy_aql import WorkerRestartPolicyOperations

class Database:
    def __init__(self, ...):
        # ... existing operations ...
        self.worker_restart_policy = WorkerRestartPolicyOperations(self._db)
```

### Step 2: Integrate into WorkerSystemService (worker_system_svc.py)

Import at top:

```python
from nomarr.components.workers import should_restart_worker, RestartDecision
```

Add instance variable for tracking pending restart timers:

```python
class WorkerSystemService:
    def __init__(self, ...):
        # ... existing init ...
        self._pending_restart_timers: dict[str, threading.Timer] = {}  # component_id -> Timer
```

Replace `on_status_change()` TODO with:

```python
if new_status == "dead":
    # Check if shutdown was requested (graceful stop)
    if self._stop_event.is_set():
        logger.info("[WorkerSystemService] Worker %s stopped gracefully, not restarting", component_id)
        return
    
    # Cancel any existing pending restart for this component (idempotent scheduling)
    existing_timer = self._pending_restart_timers.pop(component_id, None)
    if existing_timer:
        existing_timer.cancel()
        logger.debug("[WorkerSystemService] Cancelled existing restart timer for %s", component_id)
    
    # Worker died unexpectedly - consult restart policy
    restart_count, last_restart_wall_ms = self.db.worker_restart_policy.get_restart_state(component_id)
    decision = should_restart_worker(restart_count, last_restart_wall_ms)
    
    logger.info(
        "[WorkerSystemService] Restart decision for %s: %s (reason: %s)",
        component_id,
        decision.action,
        decision.reason,
    )
    
    if decision.action == "restart":
        self.db.worker_restart_policy.increment_restart_count(component_id)
        # Schedule restart with backoff (non-blocking)
        timer = threading.Timer(
            decision.backoff_seconds,
            self._restart_worker,
            args=(component_id,),
        )
        self._pending_restart_timers[component_id] = timer  # Track for idempotency
        timer.start()
    else:  # mark_failed
        self.health_monitor.set_failed(component_id)
        self.db.worker_restart_policy.mark_failed_permanent(component_id, decision.failure_reason or "Restart limit exceeded")
        logger.error(
            "[WorkerSystemService] Worker %s marked as permanently failed: %s",
            component_id,
            decision.failure_reason,
        )
```

Add private helper:

```python
def _restart_worker(self, component_id: str) -> None:
    """Restart a single worker (called after backoff delay)."""
    # Remove from pending timers (timer has fired)
    self._pending_restart_timers.pop(component_id, None)
    
    # Extract worker index from component_id ("worker:tag:0" → 0)
    try:
        worker_index = int(component_id.split(":")[-1])
    except (ValueError, IndexError):
        logger.error("[WorkerSystemService] Invalid component_id format: %s", component_id)
        return
    
    # Re-check worker_enabled (may have been disabled during backoff)
    if not self.is_worker_system_enabled():
        logger.info("[WorkerSystemService] Worker system disabled, not restarting %s", component_id)
        return
    
    # Spawn replacement worker (reuse start_all_workers logic for single worker)
    logger.info("[WorkerSystemService] Restarting worker %s", component_id)
    
    parent_conn, child_conn = Pipe(duplex=False)
    worker = create_discovery_worker(
        worker_index=worker_index,
        db_hosts=self._db_hosts,
        db_password=self._db_password,
        processor_config=self.processor_config,
        stop_event=self._stop_event,
        health_pipe=child_conn,
        execution_tier=self._tier_selection.tier if self._tier_selection else 0,
        prefer_gpu=self._tier_selection.config.prefer_gpu if self._tier_selection else True,
    )
    
    worker.start()
    child_conn.close()
    
    # Replace dead worker in list
    self._workers = [w for w in self._workers if w.worker_id != component_id]
    self._workers.append(worker)
    
    # Re-register with HealthMonitor (dead → pending)
    if self.health_monitor:
        self.health_monitor.register_component(
            component_id=worker.worker_id,
            handler=self,
            pipe_conn=parent_conn,
            policy=DEFAULT_WORKER_POLICY,
        )
    
    logger.info("[WorkerSystemService] Worker %s restarted (pid=%s)", component_id, worker.pid)
```

Modify `stop_all_workers()` to cancel pending timers:

```python
def stop_all_workers(self, timeout: float = 10.0) -> None:
    """Stop all worker processes gracefully."""
    if not self._workers:
        logger.debug("[WorkerSystemService] No workers to stop")
        return
    
    logger.info("[WorkerSystemService] Stopping %d worker(s)", len(self._workers))
    
    # Cancel all pending restart timers FIRST (before setting stop event)
    for component_id, timer in list(self._pending_restart_timers.items()):
        timer.cancel()
        logger.debug("[WorkerSystemService] Cancelled pending restart timer for %s", component_id)
    self._pending_restart_timers.clear()
    
    # Signal all workers to stop
    self._stop_event.set()
    
    # ... rest of existing stop logic (unregister, join, terminate) ...
```

### Step 3: Add unit tests

**Test file:** `tests/unit/services/test_worker_system_svc.py`

**Test:** `test_on_status_change_dead_restarts_with_backoff`

- Mock `should_restart_worker` → return `RestartDecision(action="restart", backoff_seconds=2)`
- Call `on_status_change(component_id, "healthy", "dead", context)`
- Assert `db.worker_restart_policy.increment_restart_count` called
- Assert `threading.Timer` created with 2s delay
- Assert timer tracked in `_pending_restart_timers`

**Test:** `test_on_status_change_cancels_existing_timer_before_scheduling`

- Create mock timer, add to `service._pending_restart_timers[component_id]`
- Call `on_status_change(component_id, "healthy", "dead", context)`
- Assert old timer `.cancel()` called
- Assert new timer scheduled

**Test:** `test_on_status_change_dead_marks_failed_when_limit_exceeded`

- Mock `should_restart_worker` → return `RestartDecision(action="mark_failed", failure_reason="...")`
- Call `on_status_change(...)`
- Assert `health_monitor.set_failed()` called
- Assert `db.worker_restart_policy.mark_failed_permanent()` called

**Test:** `test_on_status_change_dead_skips_restart_if_stop_requested`

- Set `service._stop_event`
- Call `on_status_change(...)`
- Assert no restart logic executed

**Test:** `test_stop_all_workers_cancels_pending_restart_timers`

- Add mock timers to `service._pending_restart_timers`
- Call `service.stop_all_workers()`
- Assert all timers `.cancel()` called
- Assert `_pending_restart_timers` cleared before `_stop_event.set()`

### Step 4: Verify with error injection

- No new errors from `get_errors()`
- Run `pytest tests/unit/services/test_worker_system_svc.py -v`
- Run `mypy nomarr/services/infrastructure/worker_system_svc.py`
- Run `ruff check nomarr/services/infrastructure/worker_system_svc.py`

### Expected Outcome

- Worker crashes → 1s delay → restart (restart_count=1)
- Crash again → 2s delay → restart (restart_count=2)
- Crash 5x in 5min → permanent failure, no more restarts
- Graceful shutdown → no restart attempt
- Shutdown with pending restart timer → timer cancelled, no restart fires
- App restart → restart_count persists → limits still enforced

---

## Notes

- This repair plan implements the exact behavior described in `docs/dev/workers.md`
- **The component (`worker_crash_comp.py`) was written correctly but never wired up** - it's sitting there waiting to be imported
- **No architectural changes needed** - just connecting existing pieces
- **Only new code required:** persistence layer (separate collection for restart counters)
- Pre-alpha policy allows schema changes without migrations
- Most of the "implementation" is copy-paste from existing `start_all_workers()` method
- **This is an attachment/cleanup task, not a feature build**

---

**Plan Status:** Ready for implementation  
**Blocking Issues:** None  
**Dependencies:** None (all code exists or is additive)
