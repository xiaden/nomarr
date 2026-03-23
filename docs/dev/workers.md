# Workers & Lifecycle

**Audience:** Developers working on worker processes, health monitoring, or debugging worker behavior.

Nomarr uses a unified discovery-based worker system for background ML processing. Workers query `library_files` for work and claim files via the `worker_claims` collection. This document describes the worker lifecycle, claim-based processing, and crash recovery.

---

## Worker Process Model

### Single Worker Type: DiscoveryWorker

**Location:** `services/infrastructure/workers/discovery_worker.py`

All workers are identical `DiscoveryWorker` processes. There are no separate scanner, calibration, or queue workers.

**Worker loop:**
1. Query `library_files` for next unprocessed file (`needs_tagging=1`)
2. Claim file by inserting a deterministic claim document into `worker_claims`
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

**Claim mechanism** uses `persistence/database/worker_claims_aql.py`:

| Operation | Method | Description |
|-----------|--------|-------------|
| Claim file | `try_claim_file(file_id, worker_id)` | Insert claim with deterministic `_key` (atomic uniqueness) |
| Release claim | `release_claim(file_id)` | Delete claim after processing |
| Get claim | `get_claim(file_id)` | Check if file is claimed |
| Worker claims | `get_claims_for_worker(worker_id)` | All claims held by a worker |
| Release all | `release_claims_for_worker(worker_id)` | Release all claims (crash recovery) |
| Cleanup stale | `cleanup_all_stale_claims(timeout_ms)` | Remove inactive/completed/ineligible claims |

**Claim document structure:**
```json
{
  "_key": "claim_{file_key}",
  "file_id": "library_files/12345",
  "worker_id": "worker:discovery:0",
  "claimed_at": 1705779600000
}
```

**Key properties:**
- **Deterministic `_key`:** Based on file `_key`; ArangoDB uniqueness prevents duplicate claims
- **One claim per file:** Only one worker can process a file at a time
- **Ephemeral:** Represents active work, not scheduled work; deleted after processing

### 3. File Processing

For each claimed file:

1. Fetch file document from `library_files`
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

### 5. Pause/Resume

`WorkerSystemService` controls workers globally via the `worker_enabled` flag in the `meta` collection:

```python
worker_svc.pause_worker_system()   # Disables processing, stops workers
worker_svc.resume_worker_system()  # Enables processing, starts workers
```

### 6. Graceful Termination

When `WorkerSystemService.stop_all_workers()` is called:

1. Service sets the shared `stop_event`
2. Workers finish current file (drain pending async writes, up to 30s)
3. Workers release VRAM promises, shut down audio loader and head pool
4. Workers close health pipe (signals EOF to parent → status transitions to `dead`)
5. If worker doesn't exit within timeout, service force-kills the process

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
3. **Consult restart policy:** `worker_restart_policy` collection tracks per-worker restart count and history
4. **Decision:**
   - **Restart:** Increment restart count, schedule replacement worker with backoff delay
   - **Mark failed:** Call `health_monitor.set_failed()` → permanent, no further monitoring

### Restart Policy

Restart decisions use `should_restart_worker(restart_count, last_restart_wall_ms)` which returns:
- `action="restart"` with `backoff_seconds` (exponential backoff)
- `action="mark_failed"` with `failure_reason` (restart limit exceeded)

**Restart state** is tracked in `worker_restart_policy` collection per component ID.

### Claim Recovery

When a worker crashes mid-file:
- Its claim document remains in `worker_claims`
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
|--------|--------|
| `start_all_workers()` | Admission control → tier selection → spawn workers |
| `stop_all_workers(timeout)` | Graceful shutdown with force-kill fallback |
| `pause_worker_system()` | Disable processing, stop workers |
| `resume_worker_system()` | Enable processing, start workers |
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
- Check restart count via `worker_restart_policy` collection
- Inspect problematic files with `ffprobe`

**Workers not processing files:**
- Verify `worker_enabled=True` (check `/api/v1/info`)
- Ensure files exist in `library_files` with tagging state needing processing
- Check worker is `healthy` (health pipe active)
- Check for orphaned claims: query `worker_claims` collection

**Consecutive error shutdown:**
- After 10 consecutive errors (`MAX_CONSECUTIVE_ERRORS`), worker shuts down
- Check logs for the error pattern and fix root cause
- Worker will be restarted by health system (if within restart limits)

### Exit Codes

| Code | Meaning |
|------|--------|
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
