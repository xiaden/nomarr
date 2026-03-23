# Health System Reference

**Audience:** Developers working on worker health monitoring, crash detection, or debugging worker behavior.

---

## Overview

Nomarr uses a **pipe/FD-based health monitoring system** for worker process lifecycle tracking and crash detection. The `HealthMonitorService` is the single source of truth for component status.

**Key properties:**
- Real-time health via OS pipes (not database polling)
- In-memory status registry owned by `HealthMonitorService`
- Domain services receive status change callbacks and own restart/recovery decisions
- DB writes are optional history snapshots (best-effort, write-only)

---

## Architecture

### Ownership Split

| Concern | Owner |
|---------|-------|
| Status tracking | `HealthMonitorService` (services/infrastructure) |
| Status types | `ComponentStatus` (helpers/dto/health_dto.py) |
| Monitoring policy | `ComponentPolicy` (helpers/dto/health_dto.py) |
| Lifecycle callbacks | `ComponentLifecycleHandler` protocol (helpers/dto/health_dto.py) |
| Restart/failure decisions | Domain services (e.g., `WorkerSystemService`) |
| Pipe creation | `WorkerSystemService` (at worker spawn time) |

### Data Flow

```
DiscoveryWorker (subprocess)
  │  writes HEALTH|{json} every 3s
  │
  └→ OS pipe (write-end)
      │
      └→ HealthMonitorService (main process, monitor thread)
          ├→ Updates in-memory status registry
          ├→ Checks staleness / deadlines
          ├→ Emits on_status_change() callback to handler
          │   └→ WorkerSystemService decides: restart? backoff? fail?
          └→ Periodically writes history snapshot to DB (optional)
```

---

## ComponentStatus

**Location:** `nomarr/helpers/dto/health_dto.py`

```python
ComponentStatus = Literal["pending", "healthy", "unhealthy", "recovering", "dead", "failed"]
```

### Status Definitions

| Status | Meaning |
|--------|--------|
| `pending` | Registered but no health frame received yet (startup phase) |
| `healthy` | Receiving regular health frames, operating normally |
| `unhealthy` | Missed one or more health frames but below death threshold |
| `recovering` | Component reported it's recovering (e.g., reloading ONNX models); has a deadline |
| `dead` | Pipe closed or missed too many frames; eligible for restart |
| `failed` | Permanently failed; no further monitoring or callbacks |

### State Machine

```
pending → healthy          (first health frame received)
pending → dead              (startup timeout exceeded)
healthy → unhealthy         (missed one staleness interval)
healthy → recovering        (frame reports status="recovering")
healthy → dead              (pipe closed)
unhealthy → healthy          (health frame received)
unhealthy → dead             (consecutive misses >= max_consecutive_misses)
unhealthy → dead             (pipe closed)
recovering → healthy         (frame reports status="healthy")
recovering → dead            (recovery deadline exceeded)
recovering → dead            (pipe closed)
dead → (unregistered)       (domain decides to restart or give up)
failed → (terminal)          (no further transitions; set via set_failed())
```

**Key invariant:** `failed` is terminal and idempotent. Once `set_failed()` is called, no further health checks, callbacks, or state transitions occur for that component.

---

## ComponentPolicy

**Location:** `nomarr/helpers/dto/health_dto.py`

```python
@dataclass
class ComponentPolicy:
    startup_timeout_s: float = 30.0     # Max time in 'pending' before -> dead
    staleness_interval_s: float = 5.0   # Seconds between expected frames
    max_consecutive_misses: int = 3     # Misses before -> dead
    min_recovery_s: float = 5.0         # Minimum recovery deadline
    max_recovery_s: float = 60.0        # Maximum recovery deadline
```

Domain services provide a `ComponentPolicy` at registration time to configure monitoring behavior per component. If omitted, defaults apply.

**Worker default policy** (from `WorkerSystemService`):
```python
DEFAULT_WORKER_POLICY = ComponentPolicy(
    startup_timeout_s=60.0,     # Workers load ONNX models at startup (slow)
    staleness_interval_s=9.0,   # Health frames every 3s; miss window = 3 intervals
    max_consecutive_misses=3,   # 3 misses = ~27s of silence before dead
    min_recovery_s=5.0,
    max_recovery_s=60.0,
)
```

---

## ComponentLifecycleHandler

**Location:** `nomarr/helpers/dto/health_dto.py`

```python
class ComponentLifecycleHandler(Protocol):
    def on_status_change(
        self,
        component_id: str,
        old_status: ComponentStatus,
        new_status: ComponentStatus,
        context: StatusChangeContext,
    ) -> None: ...
```

Domain services implement this protocol to receive callbacks when component status changes. The `HealthMonitorService` owns status tracking; the domain owns restart/backoff/failure decisions.

**`StatusChangeContext`** provides additional information:
```python
@dataclass
class StatusChangeContext:
    consecutive_misses: int = 0            # Number of missed frames
    recovery_deadline: float | None = None # When recovery must complete
    reported_recover_for_s: float | None = None  # Worker-reported recovery duration
```

**Example handler** (`WorkerSystemService.on_status_change`):
- `dead` → unregister component, apply backoff delay, spawn replacement worker
- `failed` → log permanent failure, no restart
- `unhealthy` → log warning, wait for automatic recovery or death

---

## Registration Model

Components are registered individually with `HealthMonitorService`:

```python
health_monitor.register_component(
    component_id="worker:discovery:0",    # Unique identifier
    handler=worker_system_service,         # Implements ComponentLifecycleHandler
    pipe_conn=parent_pipe_end,             # Read-end of OS pipe
    policy=ComponentPolicy(                # Optional; defaults if None
        startup_timeout_s=60.0,
        staleness_interval_s=9.0,
    ),
)
```

**Component ID format:** `worker:discovery:{index}` (e.g., `worker:discovery:0`, `worker:discovery:1`)

**Lifecycle:**
1. `WorkerSystemService` creates an OS pipe per worker
2. Worker subprocess gets the write-end; parent keeps the read-end
3. Parent calls `health_monitor.register_component()` with read-end
4. Worker sends `HEALTH|{json}` frames every 3 seconds
5. On worker death: pipe closes → `HealthMonitorService` detects → status → `dead` → callback
6. Parent calls `health_monitor.unregister_component()` during cleanup

---

## Health Frames

Workers write health frames to their pipe as prefixed JSON strings:

```
HEALTH|{"component_id":"worker:discovery:0","status":"healthy","current_job":"library_files/12345"}
```

**Frame fields:**
| Field | Type | Description |
|-------|------|-------------|
| `component_id` | `str` | Worker identifier |
| `status` | `str` | `"healthy"` or `"recovering"` |
| `current_job` | `str \| null` | File document ID if processing, null if idle |
| `recover_for_s` | `float \| null` | Requested recovery duration (only with `status="recovering"`) |

**Frame frequency:** Every 3 seconds (`HEALTH_FRAME_INTERVAL_S = 3.0` in `discovery_worker.py`)

**Frame processing:**
- `status="healthy"` → resets consecutive misses, transitions to `healthy`
- `status="recovering"` → sets recovery deadline, transitions to `recovering`
- Other status values in frames are ignored

---

## HealthMonitorService API

**Location:** `nomarr/services/infrastructure/health_monitor_svc.py`

### Constructor

```python
HealthMonitorService(
    cfg: HealthMonitorConfig,
    db: Database | None = None,  # None disables history snapshots
)
```

`HealthMonitorConfig`:
```python
@dataclass
class HealthMonitorConfig:
    monitor_poll_timeout_s: float = 1.0      # Pipe poll timeout
    history_snapshot_interval_s: int = 30     # DB snapshot frequency
```

### Key Methods

| Method | Purpose |
|--------|--------|
| `register_component(id, handler, pipe, policy)` | Start monitoring a component |
| `unregister_component(id)` | Stop monitoring, close pipe |
| `set_failed(id)` | Permanently mark as failed (terminal, idempotent) |
| `get_status(id)` | Get current status for one component |
| `get_all_statuses()` | Get all component statuses |
| `get_component_ids()` | List registered component IDs |
| `start()` | Start monitoring background thread |
| `stop()` | Stop monitoring background thread |

### Internal Architecture

A single consolidated monitor thread:
1. Polls all pipes using `multiprocessing.connection.wait()` with timeout
2. Reads frames from ready pipes
3. Checks startup timeouts, staleness intervals, and recovery deadlines
4. Emits `on_status_change()` callbacks to registered handlers

A separate history thread periodically writes status snapshots to `db.health` (best-effort, write-only).

**Design constraints:**
- Never calls `Process`/`Thread` lifecycle methods
- Never holds `Process`/`Thread` references (tracks by component_id string)
- DB writes are history-only; if DB is unavailable, health monitoring still works

---

## DB History Snapshots

Optional append-only snapshots for audit/debugging:

```json
{
  "_key": "snap_1705779600",
  "timestamp": 1705779600000,
  "components": [
    {"component_id": "worker:discovery:0", "status": "healthy", "current_job": "library_files/12345"},
    {"component_id": "worker:discovery:1", "status": "healthy", "current_job": null}
  ]
}
```

**Key invariant:** If pipe status and DB history disagree, pipe is authoritative. DB history is write-only and best-effort.

---

## Debugging

### Check Worker Health

```bash
# Via API
curl http://127.0.0.1:8356/api/v1/info
```

### View Health History (ArangoDB)

```bash
docker exec -it nomarr-arangodb arangosh \
  --server.username nomarr \
  --server.password "<password>" \
  --server.database nomarr \
  --javascript.execute-string 'db.health.toArray().forEach(d => print(JSON.stringify(d, null, 2)))'
```

### Common Issues

**Worker stuck in `pending`:**
- Worker is loading ONNX models (can take 30–60s on first run)
- Check GPU accessibility (`nvidia-smi` in container)
- If exceeds `startup_timeout_s`, transitions to `dead` automatically

**Worker flapping between `healthy` and `unhealthy`:**
- Health frames arriving inconsistently (GC pauses, I/O contention)
- Check `staleness_interval_s` relative to `HEALTH_FRAME_INTERVAL_S`
- Increase `max_consecutive_misses` in policy if needed

**Worker `dead` but process still running:**
- Pipe may be blocked (full buffer)
- Worker may be deadlocked
- `WorkerSystemService` will force-kill after timeout and spawn replacement

---

## Related Documentation

- [Workers & Lifecycle](workers.md) — DiscoveryWorker process model, claim-based processing, restart behavior
- [Architecture Overview](architecture.md) — System design and dependency direction
- [Domains](domains.md) — Workers and platform domain definitions
