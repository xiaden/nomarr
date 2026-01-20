# Workers & Lifecycle

**Audience:** Developers working on worker processes, health monitoring, or debugging worker behavior.

Nomarr uses a unified discovery-based worker system for background ML processing and library scanning. Workers query `library_files` directly for claiming work via ephemeral claim documents. This document describes the worker lifecycle, health system, health monitoring via pipe/FD channels, and runtime behavior.

---

## Worker Process Model

### Architecture

Nomarr runs a unified set of discovery-based workers, all managed by `WorkerSystemService`:

**Single Worker Type: Discovery Workers**
- Process audio files for ML inference and tag writing
- Discover work by querying `library_files` collection for `needs_tagging=true`
- Claim files via ephemeral claim documents (one file per worker at a time)
- All workers are identical; no separate scanner/calibration workers

Each worker:
- Runs in a separate Python process (`multiprocessing.Process`)
- Has its own database connection (required for multiprocessing safety)
- Reports health via pipe/FD channels (real-time, not DB-based)
- Can be paused, resumed, or terminated

### Component IDs

Workers are identified by hierarchical component IDs:
```
worker:discovery:{id}
```

Examples:
- `worker:discovery:0` - First discovery worker (typically the only one)
- `worker:discovery:1` - Second discovery worker (if scaling is enabled)

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

### 2. Discovery & Claiming Loop

While running, workers:

1. Query `library_files` for files with `needs_tagging=true`
2. Attempt to claim one file by inserting ephemeral claim document
3. If claim succeeds: process file, write tags, delete claim
4. If claim fails (another worker claimed it): try next file
5. Write health frames via pipe/FD every **5 seconds**:
   - `component`: Worker ID
   - `status`: `"healthy"` during normal operation
   - `current_job`: File ID if processing, `None` if idle
   - Optional: telemetry fields (files_processed, errors, etc.)

**Health Monitoring:** 
- Real-time health via pipe/FD (in-memory status in main process)
- DB writes are optional history-only (for audit/debugging)
- Main process detects worker death via channel closure or write failure

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

### 5. Crash Detection & Claim Recovery

The health system detects crashes via:

**Pipe/FD Channel Closure:**
- Main process detects pipe closure or write failure
- Indicates worker died unexpectedly
- Main process marks worker as `crashed`

**Ephemeral Claim Cleanup:**
- When a worker crashes mid-file, its claim document is ephemeral (no TTL)
- Crashed worker's claim can be manually cleaned up or auto-expires
- File remains in `library_files` with `needs_tagging=true`
- Next healthy worker will pick it up automatically
- No file gets stuck; just re-processed by next available worker

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

## Health System: Pipe/FD Channels

### Real-Time Health (Single Source of Truth)

Workers write health frames to pipe/FD channels (in-memory in main process):

**Frame Format:**
```
HEALTH|{"component_id":"worker:discovery:0","status":"healthy","current_job":"file_123"}
```

**Frame Frequency:** Every 5 seconds (configurable)

**Channel Model:**
- Main process creates one pipe per worker at spawn time
- Worker writes periodic frames to that pipe
- Main process reads frames, updates in-memory status registry
- HealthMonitor polls registry for status snapshot

### Database History (Write-Only, Optional)

Optional append-only collection for audit/debugging:

```json
{
  "_key": "snap_2025_01_20_001",
  "timestamp": 1705779600000,
  "components": [
    {"component_id": "worker:discovery:0", "status": "healthy", "current_job": "file_123"},
    {"component_id": "worker:discovery:1", "status": "healthy", "current_job": null}
  ]
}
```

**Key invariant:** If pipe is wrong, fix pipe—do not maintain dual real-time paths.

### Main Process Death Detection

Workers detect main process death via channel closure:
- Worker writes frame fails (broken pipe)
- Worker logs, finishes current file, exits gracefully
- No orphaned claims (worker dies before inserting claim, or deletes claim before exiting)

### Status State Machine

```
starting → healthy ↔ paused → stopped
    ↓
  crashed
```

**State Values:**

- `starting`: Worker process spawned, ML models initializing
- `healthy`: Normal operation, claiming and processing files
- `paused`: Not claiming new files (current file completes)
- `crashed`: Pipe closed or worker exited unexpectedly
- `stopped`: Graceful shutdown (no active work)

### Invariants

1. **Ephemeral Claims:** Claim documents have no TTL; they represent active work
2. **Single Writer:** Each worker writes only to its own pipe (no conflicts)
3. **Frame Frequency:** Workers write frames every ~5 seconds
4. **Status Consistency:** `status='healthy'` requires recent frame (< 30s old)
5. **Channel Closure:** Broken pipe = worker death (automatic detection by main process)
6. **Claim Cleanup:** Worker cleans up claim after processing file (before next claim or on exit)

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
# Via API
curl http://localhost:8356/api/v1/info
```

### View Worker Logs

```bash
# All workers
docker logs nomarr

# Filter for specific worker
docker logs nomarr 2>&1 | grep "worker:discovery:0"
```

### Common Issues

**Worker stuck in 'starting' state:**
- Check if ML models are loading (may take 30-60s on first run)
- Verify GPU is accessible (`nvidia-smi` in container)
- Check disk space for database writes

**Worker keeps crashing:**
- Review logs for exceptions or error codes (look for specific file paths that trigger crashes)
- Check restart count in health system
- Verify file permissions on database and music library
- Check available VRAM (effnet requires 9GB)
- If specific files consistently crash workers, inspect with `ffprobe` or audio editor (may be corrupted)

**Workers not processing files:**
- Verify `worker_enabled=True` (check `/api/v1/info`)
- Ensure files exist in `library_files` with `needs_tagging=true`
- Check worker is `healthy` (pipe/FD channel active)
- Check for orphaned claims: query `library_file_claims` collection for stale claims

**Database lock errors:**
- Each worker creates its own database connection on spawn
- If seeing "database is locked" errors, verify ArangoDB MVCC is working
- Check for stuck transactions in database logs

---

## Advanced Topics

### Worker Process Communication via Pipe/FD

Workers use **pipe/FD channels for real-time health** (no database IPC):

1. Main process creates one pipe per worker at spawn time
2. Workers write periodic health frames to their pipe
3. Main process reads frames, updates in-memory status registry
4. HealthMonitor queries registry for snapshots
5. Web UI receives status via API endpoint (not SSE)

This architecture ensures:
- Real-time health without database polling
- Immediate crash detection via pipe closure
- Multiprocessing safety (no shared memory)
- Minimal latency and overhead

**Pipe Frame Format:**
```
HEALTH|{"component_id":"worker:discovery:0","status":"healthy","current_job":"file_123"}
```

### Claim Document Structure

When a worker claims a file for processing, it creates an ephemeral claim document:

```json
{
  "_key": "file_123_claim_worker0",
  "file_id": "file_123",
  "claimed_by": "worker:discovery:0",
  "claimed_at": 1705779600000,
  "ttl": null
}
```

**Key Properties:**
- **Ephemeral (no TTL):** Represents active work, not scheduled work
- **Unique per file:** Only one worker can hold claim at a time
- **Auto-cleanup:** Worker deletes claim after processing file
- **Crash recovery:** Stale claims can be manually cleaned up; file remains in `needs_tagging=true`

### Debugging Pipe Health

```bash
# Check pipe file descriptors for a running worker
lsof -p $(docker inspect -f '{{.State.Pid}}' nomarr) | grep pipe

# Monitor pipe writes in real time
strace -p $(docker inspect -f '{{.State.Pid}}' nomarr) -e write
```

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

- [Health System](health.md) - Detailed health monitoring via pipe/FD channels
- [Calibration Refactor](CALIBRATION_REFACTOR.md) - Historical background on discovery worker design
- [Services Layer](services.md) - WorkerSystemService API reference
