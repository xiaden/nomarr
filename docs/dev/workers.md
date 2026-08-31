# Workers & Lifecycle

**Audience:** Developers working on worker processes, health monitoring, or debugging worker behavior.

Nomarr uses a unified discovery-based worker system for background ML processing. Workers query `songs` for work and claim files via the `worker_claims` table. This document describes the worker lifecycle, claim-based processing, and crash recovery.

---

## Worker Process Model

### Single Worker Type: DiscoveryWorker

**Location:** `services/infrastructure/workers/discovery_worker.py`

All workers are identical `DiscoveryWorker` processes. There are no separate scanner, calibration, or queue workers.

**Worker loop:**

1. Query `songs` for next unprocessed file (`needs_tagging=1`)
2. Claim file by inserting a deterministic claim row into `worker_claims`
3. Process file using `process_file_workflow` (ONNX backbone + heads → tags)
4. Execute deferred DB writes (tags, model outputs, segment stats) on background thread
5. Release claim
6. Repeat immediately (no sleep between files; sleep only when idle)

Each worker:

- Runs in a separate Python process (`multiprocessing.Process`)
- Creates its own `Database` connection (process isolation)
- Reports health via OS pipe to `HealthMonitorService` (see [Health System](health.md))
- Manages its own ONNX model cache with lazy warmup and idle eviction

### Component IDs

Workers are identified by hierarchical component IDs:

```
worker:discovery:{index}
```

Examples: `worker:discovery:0`, `worker:discovery:1`

---

## Background Tasks (BTS)

Nomarr also uses an in-process **Background Task Service (BTS)** for lightweight background work that should stay in the main application process.

This is **not** the same as the multiprocessing worker system documented above:

 | Mechanism | Runtime model | Best for |
 | ----------- | --------------- | ---------- |
 | `BackgroundTaskService` | `threading.Thread` in the API process | Short-to-medium in-process background work, such as write-tags dispatch |
 | `DiscoveryWorker` pool | `multiprocessing.Process` subprocesses | Isolated ML file processing, claim-based discovery, and crash recovery |

Use BTS when the task should share the application's existing services and process state. Use worker processes when the task needs isolation, separate process lifecycle management, or the full discovery/claim pipeline.

### ManagedTask API

`BackgroundTaskService.start_task()` accepts a `ManagedTask` object:

```python
from functools import partial

from nomarr.helpers import ManagedTask

task = ManagedTask(
    task_id="write_tags:<library.name>",
    fn=partial(tagging_service.write_tags_to_files, library),
)
```

`ManagedTask` fields:

 | Field | Purpose |
 | ------- | --------- |
 | `task_id` | Stable identifier used for deduplication, cancellation, and polling |
 | `fn` | Zero-argument callable executed on the background thread; prefer `functools.partial(...)` when you need to bind arguments |
 | `stop_event` | Cooperative cancellation signal checked by the task at safe checkpoints |
 | `on_complete` | Optional callback invoked after the task's work succeeds. BTS records `complete` only once this callback itself succeeds; if it raises, the task is recorded as `error` instead |
 | `daemon` | Whether the thread runs as a daemon; BTS tasks default to `True` |

### Canonical Dispatch Example: Write-Tags

The write-tags flow is the canonical BTS example. `TaggingService.start_write_tags_background()` builds a task ID, defines the reconcile loop, and submits it through BTS:

```python
import threading

library = library_service.get_library_by_name("library_name")
stop_event = threading.Event()
task_id = tagging_service.start_write_tags_background(
    library,
    stop_event,
    on_complete=lambda: navidrome_service.trigger_rescan(),
)
```

Inside the service, the task is dispatched as a managed in-process thread:

```python
from nomarr.helpers import ManagedTask

task_id = self._bts.start_task(
    ManagedTask(
        task_id=f"write_tags:{library.name}",
        fn=_task,
        stop_event=stop_event,
        on_complete=on_complete,
        daemon=True,
    ),
)
```

The `_task` function loops until the library is fully reconciled (`remaining == 0`) or cancellation is requested.

### Cancellation Protocol

BTS uses **cooperative** cancellation — it never forcibly kills threads:

1. Call `bts.cancel_task(task_id)` to signal cancellation, or `bts.cancel_and_join(task_id, timeout)` to signal *and* wait for the task to finish
2. BTS sets the task's `stop_event` and returns immediately
3. The task exits cooperatively when it next checks `stop_event.is_set()`

Example:

```python
was_signaled = bts.cancel_task("write_tags:<library.name>")

if was_signaled:
    logger.info("Write-tags cancellation requested")
```

Tasks should check `stop_event.is_set()` at natural checkpoints inside loops, before starting another batch, or before expensive follow-up work. BTS does not forcibly kill threads.

A task that stops cooperatively with work still pending is **not** considered complete: it records `{"status": "cancelled"}` and its `on_complete` callback is skipped. For the write-tags flow this keeps the library's `tag_write` axis resumable — `pipeline_svc.stop_write()` resets it back to `not_written` so pending writes can be re-dispatched later.

### Status Querying

Use `bts.get_task_status(task_id)` to inspect current state:

```python
status = bts.get_task_status("write_tags:<library.name>")
```

Return values:

- `{"status": "running"}` while the task is active
- `{"status": "complete"}` after the task's work *and* its `on_complete` callback both succeed
- `{"status": "cancelled"}` after cooperative cancellation (the task stopped at a checkpoint with work pending; `on_complete` is skipped)
- `{"status": "error"}` if the task raised an exception, or if its `on_complete` callback raised
- `None` if BTS has never seen that `task_id`

Interface code can combine BTS status with database state for richer polling responses, such as "pending files remaining" plus "is a background reconcile loop still running?"

---

## Lifecycle

### 1. Spawn

When `WorkerSystemService.start_all_workers()` is called:

1. **Admission control** runs: GPU capability check → capacity probe → tier selection → worker count
2. Service creates one OS pipe per worker (read-end for parent, write-end for worker)
3. Service spawns `DiscoveryWorker` as `multiprocessing.Process` with stagger delay (2s between workers)
4. Service registers each worker with `HealthMonitorService` (pipe + policy + callback handler)
5. Worker subprocess:
   - Configures subprocess logging
   - Starts health writer thread (sends `HEALTH|{json}` frames every 3s)
   - Checks ML backend availability (ONNX Runtime)
   - Creates its own `Database` connection
   - Clears any stale VRAM promises from previous crashes
   - Transitions to `healthy` status

### 2. Discovery & Claiming

**Work discovery** uses `components/workers/worker_discovery_comp.py`:

```python
file_id = discover_and_claim_file(
    db,
    worker_id="worker:discovery:0",
    min_duration_s=config.min_duration_s,
    allow_short=config.allow_short,
)
```

**Claim mechanism** goes through the `db.app` intent facade (post-ADR-040 sync persistence). Worker claims live in the `worker_claims` table; worker processes never touch it directly — they use `AppDb` methods:

 | Operation | AppDb method | Description |
 | ----------- | ------------ | ------------- |
 | Claim file | `db.app.add_claim(payload) -> int` | Insert claim; deterministic `key` (`claim_<song_id>`) enforces atomic uniqueness — raises `DuplicateEntityError` if already claimed |
 | Release claim | `db.app.remove_claim(song_id)` | Delete one song's claim after processing |
 | Bulk release | `db.app.remove_claims(worker_ids=..., song_ids=...)` | Delete claims matching worker ids and/or song ids; returns count removed |
 | List claims | `db.app.list_claims() -> list[WorkerClaimRow]` | All claims (each row carries `id`, `worker_id`, `key`, `value`, `claimed_at`) |

 **Claim payload structure** (the dict passed to `add_claim`; stored as the row's `value` JSONB):

 ```json
 {
   "key": "claim_12345",
   "file_id": "12345",
   "worker_id": "worker:discovery:0",
   "claimed_at": 1705779600000
 }
 ```

 **Key properties:**

 - **Deterministic claim key:** `key` is `claim_<song_id>`; the database uniqueness constraint prevents duplicate claims (insertion raises `DuplicateEntityError`)
 - **One claim per file:** Only one worker can process a song at a time
 - **Ephemeral:** Represents active work, not scheduled work; deleted after processing

### 3. File Processing

For each claimed file:

1. Fetch song row from `songs`
2. Lazy-warm ONNX model cache on first file (avoids VRAM allocation until work arrives)
3. Run `process_file_workflow` (audio load → mel spectrogram → backbone embedding → head inference → tag aggregation)
4. Submit deferred DB writes to background thread (overlaps I/O with next file's ML)
5. Trim glibc heap to release freed numpy arrays back to OS
6. Release claim (via deferred write chain, or immediately on skip/error)

**Resource management:** If both VRAM and RAM are exhausted, the worker releases the claim, enters `recovering` status (reported via health frame), and waits 30 seconds before retrying.

### 4. Idle Behavior

When no work is found:

- Sleep for 1 second between polls (`IDLE_SLEEP_S`)
- After 40 seconds idle (`CACHE_IDLE_TIMEOUT_S`), evict ONNX model cache to free VRAM
- After enough idle polls, spawn background vector promotion thread

### Idle-Path Pipeline Trigger

The worker idle path also advances the library automation pipeline.

When `discover_and_claim_file()` returns `None`, the subprocess checks `find_ml_complete_libraries(db, ...)` (in `nomarr/components/library/library_records_comp.py`) for libraries still in `ml_running` whose untagged file count has reached zero. For each completed library, the worker transitions the pipeline state to:

- `awaiting_calibration` when the tagged file count meets the calibration minimum
- `too_small` when the library is fully tagged but still below that minimum

If at least one transition fires, the worker sends a pipeline frame over the existing health pipe:

```text
PIPELINE|calibration_trigger
```

`HealthMonitorService` reads that frame in the main process and forwards it through the registered pipeline callback. `WorkerSystemService` wires the callback directly to `pipeline_svc.trigger_calibration()`, keeping calibration dispatch in the main process where `BackgroundTaskService`, `CalibrationService`, and the other long-lived services already live.

### 5. Pause/Resume

`WorkerSystemService` controls workers globally via the `worker_enabled` flag in the `meta` table:

```python
worker_svc.disable_worker_system()  # Disables processing, stops workers
worker_svc.enable_worker_system()  # Enables processing, starts workers
```

### 6. Graceful Termination

When `WorkerSystemService.stop_all_workers()` is called:

1. Service sets `self._shutting_down = True` to gate restart decisions during global shutdown
2. Service cancels all pending restart timers (no new restarts while shutting down)
3. Each worker receives a signal via its **own per-worker `multiprocessing.Event`** (created in `_spawn_worker()` or `_restart_worker()`)
4. Workers finish current file (drain pending async writes, up to 30s)
5. Workers release VRAM promises, shut down audio loader and head pool
6. Workers close health pipe (signals EOF to parent → status transitions to `dead`)
7. If worker doesn't exit within timeout, service force-kills the process

The `_shutting_down` flag is checked in `_handle_worker_death()` and `_restart_worker()` — when set, death events are logged but no restart is attempted, and pending restarts are skipped.

---

## Crash Recovery

Crash recovery is coordinated between `HealthMonitorService` and `WorkerSystemService`.

### Detection

`HealthMonitorService` detects worker death via:

- **Pipe closure:** Worker process exits → pipe EOF → immediate `dead` status
- **Staleness:** Worker stops sending health frames → `healthy` → `unhealthy` → `dead` (after `max_consecutive_misses`)
- **Startup timeout:** Worker never sends first frame → `pending` → `dead`

See [Health System](health.md) for the full status state machine.

### Recovery Flow

When `HealthMonitorService` transitions a worker to `dead`, it calls `WorkerSystemService.on_status_change()`:

1. **Release file claims:** `release_claims_for_worker(worker_id)` frees all claimed files for rediscovery
2. **Release VRAM promises:** Reclaims fleet headroom from the dead worker
3. **Consult restart policy:** `worker_restart_policy` table tracks per-worker restart count and history
4. **Decision:**
   - **Restart:** Increment restart count, schedule replacement worker with backoff delay
   - **Mark failed:** Call `health_monitor.set_failed()` → permanent, no further monitoring

### Restart Policy

Restart decisions use `should_restart_worker(restart_count, last_restart_wall_ms)` which returns:

- `action="restart"` with `backoff_seconds` (exponential backoff)
- `action="mark_failed"` with `failure_reason` (restart limit exceeded)

**Restart state** is tracked in `worker_restart_policy` table per component ID.

### Claim Recovery

When a worker crashes mid-file:

- Its claim row remains in `worker_claims`
- `WorkerSystemService.on_status_change("dead")` immediately releases the claim
- The file returns to `needs_tagging=1` state and becomes rediscoverable
- The replacement worker (or any other worker) will pick it up

Additionally, `WorkerSystemService.cleanup_stale_claims()` can be called periodically to catch edge cases.

---

## WorkerSystemService

**Location:** `services/infrastructure/worker_system_svc.py`

Manages the worker pool lifecycle and implements `ComponentLifecycleHandler` for health callbacks.

### Key Methods

 | Method | Purpose |
 | -------- | -------- |
 | `start_all_workers()` | Admission control → tier selection → spawn workers |
 | `stop_all_workers(timeout)` | Graceful shutdown with force-kill fallback |
 | `add_workers(n)` | Dynamically add n workers to the pool (no admission control re-run) |
 | `remove_workers(n)` | Dynamically drain and remove n workers from end of pool |
 | `disable_worker_system()` | Disable processing, stop workers |
 | `enable_worker_system()` | Enable processing, start workers |
 | `is_running()` | Check if any workers are running |
 | `get_workers_status()` | Worker pool status dict |
 | `get_resource_status()` | GPU/CPU tier and capacity info |
 | `cleanup_stale_claims()` | Remove orphaned claims |
 | `on_status_change(...)` | Health callback → restart/fail decisions |

### Admission Control

Before spawning workers, `WorkerSystemService` runs admission control:

1. **GPU capability check:** `nvidia-smi` succeeds? (cached at startup)
2. **Capacity probe:** Measure available GPU/CPU resources
3. **Tier selection:** Choose execution tier (0–4)
   - Tier 0–3: Workers started with varying resource allocation
   - Tier 4: Refusal — no workers started (insufficient resources)
4. **Worker count:** Calculated based on tier and available resources

---

## VRAM Probe & OOM Self-Healing

On first startup (and after model files change), Nomarr measures how much VRAM each ONNX model actually consumes before allowing GPU placement. Results are stored in `meta` under `ml_model_vram:<model_path>` keys and reused across restarts.

### Initial Probe

`_warm_onnx_cache()` in the discovery worker calls `has_model_vram_measurements()` before the cache is warmed. If no measurements exist, it runs `probe_all_models()`, which:

1. Warms the CUDA context with a minimal identity model (~400–600 MB overhead, not attributed to any backbone)
2. Loads each backbone and head model on GPU sequentially (only one live at a time)
3. Records peak VRAM delta with 10% headroom (`measured_bytes * 1.1`)
4. Writes the result to `meta.ml_model_vram:<path>` (bytes as string)

If a model fails to load or falls back to CPU (silent CUDA EP rejection), it is recorded as `sys.maxsize` — the coordinator will then immediately reject GPU placement for that model without wasting a real attempt.

### OOM Self-Healing During Inference

ONNX Runtime's BFC arena grows dynamically and can OOM mid-inference even if the initial load succeeded (e.g. model needs more memory for a longer input sequence than the probe used). When this happens inside `BaseONNXModel.run()`:

1. The BFC error message is parsed to extract the **requested byte count**
2. The stored probe value is bumped by **25%** via `update_model_vram_from_oom()`
3. The model is unloaded and reloaded on GPU with the updated VRAM cap
4. If the coordinator rejects the new (larger) promise — not enough free headroom — the model falls back to **CPU** automatically
5. The loop repeats until inference succeeds or the model is running on CPU

This means the first few processing runs after a fresh install (or after models change) may trigger OOM → reprobe cycles. **This is expected behavior.** Each cycle produces a `[vram_probe] OOM self-heal` warning log and progressively converges the stored limit toward the model's true peak requirement. Once stabilized, the measurements are reused and no further OOM cycles occur under normal conditions.

---

## Debugging

### Check Worker Status

```bash
# Via API
curl http://127.0.0.1:8356/api/v1/info
```

### View Worker Logs

```bash
# All workers
docker logs nomarr

# Filter for specific worker
docker logs nomarr 2>&1 | grep "worker:discovery:0"
```

### Common Issues

**Worker stuck in `pending`:**

- ONNX model loading can take 30–60s on first run
- Check GPU accessibility (`nvidia-smi` in container)
- Startup timeout (`startup_timeout_s=60.0` default) will transition to `dead` automatically

**Worker keeps crashing:**

- Check logs for specific file paths causing crashes
- Verify VRAM availability (effnet backbone requires significant GPU memory)
- Check restart count via `worker_restart_policy` table
- Inspect problematic files with `ffprobe`

**`[vram_probe] OOM self-heal` warnings on startup:**

- Expected on first run or after model files change — see [VRAM Probe & OOM Self-Healing](#vram-probe--oom-self-healing)
- Each warning bumps the stored VRAM cap by 25% and reloads
- Cycles converge within a few files; logs should stop once limits stabilize
- If a model consistently ends up on CPU after several cycles, the GPU simply does not have enough free headroom for it at that time

**Workers not processing files:**

- Verify `worker_enabled=True` (check `/api/v1/info`)
- Ensure files exist in `songs` with tagging state needing processing
- Check worker is `healthy` (health pipe active)
- Check for orphaned claims: query `worker_claims` table

**Consecutive error shutdown:**

- After 10 consecutive errors (`MAX_CONSECUTIVE_ERRORS`), worker shuts down
- Check logs for the error pattern and fix root cause
- Worker will be restarted by health system (if within restart limits)

### Exit Codes

 | Code | Meaning |
 | ------ | -------- |
 | `0` | Clean exit |
 | `1` | Uncaught exception |
 | `130` | SIGINT (Ctrl+C) |
 | `137` | SIGKILL |
 | `143` | SIGTERM |

---

## Related Documentation

- [Health System](health.md) — Pipe/FD-based health monitoring, ComponentStatus state machine, ComponentPolicy
- [Architecture Overview](architecture.md) — System design, layer structure, data flow
- [Domains](domains.md) — Workers domain (claims, crash recovery) and platform domain
- [Migrations](migrations.md) — Database migration system
