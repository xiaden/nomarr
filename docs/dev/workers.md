# Workers & Lifecycle

**Audience:** Developers working on worker processes, health monitoring, or debugging worker behavior.

Nomarr uses dedicated worker processes for background processing of tagging, library scanning, and recalibration jobs. This document describes the worker lifecycle, health system, restart semantics, and runtime behavior.

---

## Worker Process Model

### Architecture

Nomarr runs three types of workers, each managed by `WorkerSystemService`:

1. **Tag Workers** - Process audio files for ML inference and tag writing
2. **Library Workers** - Scan filesystem for new/changed files and queue them
3. **Calibration Workers** - Recalibrate existing tags with updated thresholds

Each worker:
- Runs in a separate Python process (`multiprocessing.Process`)
- Has its own database connection (required for multiprocessing safety)
- Reports health via heartbeats to the `health` table
- Can be independently paused, resumed, or terminated

### Component IDs

Workers are identified by hierarchical component IDs:

```
worker:{queue_type}:{id}
```

Examples:
- `worker:tag:0` - First tag worker (usually the only one)
- `worker:library:0` - Library scanner worker
- `worker:calibration:0` - Calibration worker

---

## Worker Lifecycle

### 1. Spawn

When `WorkerSystemService.start_workers()` is called:

1. Service creates a `multiprocessing.Process` for each worker type
2. Worker process starts and creates its own `Database` connection
3. Worker writes initial heartbeat with `status='starting'` to `health` table
4. Worker enters main processing loop
5. Within ~5 seconds, status transitions to `status='healthy'`

**Database Safety:** Each worker creates its own ArangoDB connection via `Database()`. The python-arango client handles connection pooling internally.

### 2. Heartbeat Loop

While running, workers:

1. Check for pending jobs in their queue
2. Process jobs one at a time (single-threaded within each worker)
3. Write heartbeat every **5 seconds** via `health` table:
   - `component`: Worker ID
   - `last_seen`: Current timestamp (milliseconds)
   - `status`: `"healthy"` during normal operation
   - `pid`: Process ID
   - `current_job`: Job ID if processing, `None` if idle
   - `details_json`: Serialized metadata (queue stats, error counts, etc.)

**Heartbeat Timeout:** If a worker doesn't update `last_seen` within **30 seconds**, the health system marks it as unhealthy.

### 3. Pause

When `WorkerSystemService.pause_all_workers()` is called:

1. Service sets global `worker_enabled=False` flag
2. Workers finish their **current job** (no interruption)
3. Workers stop picking up new jobs
4. Workers continue heartbeating with `status='healthy'` but `current_job=None`
5. Worker processes remain alive but idle

**Resume:** Calling `resume_all_workers()` sets `worker_enabled=True` and workers resume processing immediately.

### 4. Graceful Termination

When `WorkerSystemService.stop_workers()` is called:

1. Service sends termination signal to each worker process
2. Worker writes `status='stopping'` to `health` table
3. Worker completes current job if processing one (up to 10 seconds)
4. Worker cleans up resources (closes DB connection, flushes logs)
5. Worker exits with code `0` (clean exit)

If worker doesn't exit within **10 seconds**, service sends `SIGTERM` to force termination.

### 5. Crash Detection & Job Recovery

The health system detects crashes via:

**Heartbeat Timeout:**
- Worker's `last_seen` timestamp exceeds 30 seconds
- Health system marks worker as `status='crashed'`

**Exit Code Monitoring:**
- Service detects non-zero exit codes
- Nomarr-specific codes:
  - `-1`: Fatal error during initialization
  - `-2`: Database corruption detected
  - `-3`: ML model loading failed
- Standard Python exit codes indicate exceptions

**Automatic Job Recovery:**
- When a worker crashes mid-job, the interrupted job is automatically requeued
- Jobs have a crash counter (max 2 retries) to prevent infinite loops from problematic files
- After exceeding retry limit, job is marked as "error" (toxic job) and will not be requeued
- This distinguishes worker crashes (infrastructure issues) from file-level failures (bad audio files)

### 6. Automatic Restart

When a worker crashes:

1. Health system marks worker as `crashed` in DB
2. `WorkerSystemService` requeues any interrupted job (if applicable)
3. Service increments `restart_count` for that worker
4. Service waits for **exponential backoff delay**: `min(2^N seconds, 60s)`
   - First restart: 1 second
   - Second restart: 2 seconds
   - Third restart: 4 seconds
   - Fourth restart: 8 seconds
   - Fifth+ restart: 16, 32, 60 seconds (capped at 60)
5. Service spawns new worker process with same component ID
6. New worker's `restart_count` carries over from crashed worker

**Two-Tier Restart Limiting:**

Nomarr uses two-tier limits to catch both rapid crashes (OOM loops) and slow thrashing:

1. **Rapid Restart Limit:** 5 restarts within **5 minutes**
   - Catches tight crash loops (e.g., immediate OOM on startup)
   - Worker marked `status='failed'` and stops restarting

2. **Lifetime Restart Limit:** 20 restarts **total**
   - Catches slow thrashing (e.g., crashes every 30 minutes for hours)
   - Worker marked `status='failed'` after 20th restart regardless of timing

**Manual Recovery:**
- Failed workers are **not** automatically restarted
- Manual intervention required: check logs, fix root cause, call `resume_all_workers()`
- Restart counts reset after successful 5+ minute operation

**Restart Count Persistence:**
- Restart counts persist across pause/resume cycles
- Prevents bypassing limits by toggling pause/resume
- Counts cleared only on manual service restart or after successful operation window

---

## Health Table Structure

Workers communicate state via the `health` table:

| Column | Type | Description |
|--------|------|-------------|
| `component` | TEXT PRIMARY KEY | Worker ID: `worker:{type}:{id}` |
| `last_seen` | INTEGER | Timestamp (ms since epoch) of last heartbeat |
| `status` | TEXT | Current status: `starting`, `healthy`, `stopping`, `crashed`, `failed` |
| `pid` | INTEGER | Process ID (for debugging and termination) |
| `current_job` | INTEGER | Job ID if processing, `NULL` if idle |
| `details_json` | TEXT | JSON metadata (queue stats, error counts, version) |
| `restart_count` | INTEGER | Total number of restarts (lifetime counter) |
| `last_restart` | INTEGER | Timestamp (ms) of most recent restart |
| `created_at` | INTEGER | Timestamp (ms) when worker first registered |

### Job Crash Counters

Jobs that are interrupted by worker crashes have their own crash counter tracked in the `meta` table:

- **Key format:** `job_crash_count:{queue_type}:{job_id}`
- **Max retries:** 2 (job requeued up to 2 times after crashes)
- **Toxic job detection:** After 2 crash retries, job marked as "error" and not requeued
- **Purpose:** Prevents infinite loops from problematic audio files that consistently crash workers
- **Separate from worker restarts:** Job crash counter is independent of worker restart limits

Example: If a corrupted audio file crashes a worker 3 times, the job is marked toxic and skipped, but the worker continues processing other jobs normally.

### Status State Machine

```
starting → healthy ↔ stopping
    ↓          ↓
  crashed   crashed → failed
```

**State Transitions:**

- `starting`: Worker process spawned, initializing resources
- `healthy`: Normal operation, heartbeating every 5s
- `stopping`: Graceful shutdown in progress
- `crashed`: Heartbeat timeout (>30s) or abnormal exit detected
- `failed`: Too many restarts (5 within 5 minutes), manual recovery required

### Invariants

1. **Ephemeral Data:** Health table is cleared on service startup (workers from previous runs are stale)
2. **Single Writer:** Each worker writes only its own row (no conflicts)
3. **Heartbeat Frequency:** Workers MUST update `last_seen` at least every 30 seconds
4. **Status Consistency:** `status='healthy'` requires `last_seen` within last 30 seconds
5. **PID Uniqueness:** Each worker has unique PID (enforced by OS)

---

## Pause/Resume Behavior

### Global Control

The `worker_enabled` flag (stored in `meta` table) controls all workers globally:

```python
# Pause all workers
service.pause_all_workers()  # Sets worker_enabled=False

# Resume all workers
service.resume_all_workers()  # Sets worker_enabled=True
```

### Per-Worker Behavior

When paused:
- Workers check `worker_enabled` flag before picking up new jobs
- Current job completes normally (no interruption mid-processing)
- Workers remain alive, heartbeating, but idle (`current_job=None`)
- Resume takes effect immediately (next poll cycle, typically <2s)

### Restart Count Preservation

Pause/resume **does not** reset restart counts:
- If a worker has crashed 3 times, pausing and resuming keeps count at 3
- This prevents users from bypassing restart limits by toggling pause
- Restart counts only reset after 5 minutes of successful operation

---

## Exit Codes

### Nomarr-Specific Codes

| Code | Meaning | Action |
|------|---------|--------|
| `0` | Clean exit | Normal - no restart needed |
| `-1` | Fatal initialization error | Logged, automatic restart attempted |
| `-2` | Database corruption | Logged, automatic restart attempted |
| `-3` | ML model loading failed | Logged, automatic restart attempted |

### Standard Python Codes

| Code | Meaning |
|------|---------|
| `1` | Uncaught exception |
| `2` | Command-line usage error (shouldn't occur in workers) |
| `130` | Terminated by SIGINT (Ctrl+C) |
| `137` | Killed by SIGKILL |
| `143` | Terminated by SIGTERM |

---

## Debugging Workers

### Check Worker Health

```bash
# Via CLI
docker exec nomarr python -m nomarr.cli health

# Via API
curl http://localhost:8356/api/v1/info
```

### View Worker Logs

```bash
# All workers
docker logs nomarr

# Filter for specific worker
docker logs nomarr 2>&1 | grep "worker:tag:0"
```

### Common Issues

**Worker stuck in 'starting' state:**
- Check if ML models are loading (may take 30-60s on first run)
- Verify GPU is accessible (`nvidia-smi` in container)
- Check disk space for database writes

**Worker keeps crashing:**
- Check `restart_count` in health table (if ≥5 rapid or ≥20 lifetime, it's marked failed)
- Review logs for exceptions or error codes (look for specific file paths that trigger crashes)
- Check for toxic jobs: Query `meta` table for keys like `job_crash_count:tag:*` with values ≥2
- Verify file permissions on database and music library
- Check available VRAM (effnet requires 9GB)
- If specific files consistently crash workers, they'll be marked as "error" after 2 retries

**Jobs stuck in error state:**
- Check if job crash counter exceeded limit (marked as toxic job)
- Review file that caused crash: may be corrupted, invalid format, or triggering model bug
- Manually inspect problem file with `ffprobe` or audio editor
- If file is valid, consider reporting issue with model or increasing retry limit

**Workers not processing jobs:**
- Verify `worker_enabled=True` (check `/api/v1/info`)
- Ensure jobs exist in queue (`queue_depth` > 0)
- Check worker is `healthy` and `current_job=None` (idle but alive)

**Database lock errors:**
- Workers must NOT share database connections
- Each worker creates its own connection on spawn
- If seeing "database is locked" errors, verify multiprocessing safety

---

## Advanced Topics

### Custom Worker Implementation

To add a new worker type:

1. Define queue type in `QueueType` enum
2. Implement worker loop function in `nomarr/components/workers/`
3. Register worker in `WorkerSystemService._spawn_workers()`
4. Add health monitoring via `HeartbeatWriter` utility
5. Handle pause signals via `worker_enabled` flag checks

### Worker Process Communication

Workers use **database-based IPC** (no shared memory or pipes):

1. Workers write heartbeats to `health` table
2. `StateBroker` polls `health` table every 1-2 seconds
3. Broker broadcasts changes via Server-Sent Events (SSE)
4. Web UI receives real-time updates via EventSource

This architecture ensures:
- Multiprocessing safety (ArangoDB MVCC handles concurrent access)
- No shared state between processes
- Crash resilience (workers can restart independently)
- Debuggability (all state persisted in DB collections)

### Restart Backoff Formula

```python
delay_seconds = min(2 ** restart_count, 60)
```

Examples:
- 0 restarts: 1s (2^0)
- 1 restart: 2s (2^1)
- 2 restarts: 4s (2^2)
- 3 restarts: 8s (2^3)
- 4 restarts: 16s (2^4)
- 5 restarts: 32s (2^5)
- 6+ restarts: 60s (2^6=64, capped at 60)

This exponential backoff prevents restart storms while allowing quick recovery from transient failures. The 60-second cap ensures workers don't wait excessively long between restart attempts.

---

## Related Documentation

- [Health System](health.md) - Detailed health table invariants and operations
- [StateBroker & SSE](statebroker.md) - Real-time state broadcasting
- [Queue System](queues.md) - Job queuing and processing
- [Services Layer](services.md) - WorkerSystemService API reference
