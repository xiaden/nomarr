# Health System Reference

**Health Table Schema, Operations, and Invariants**

---

## Overview

Nomarr uses a **health table** for worker process monitoring and crash detection. This is the primary mechanism for:

- Tracking worker liveness (heartbeats)
- Detecting crashes (missed heartbeats)
- Coordinating pause/resume operations
- Tracking restart counts and history

**Key principle:** Workers write to health table; coordinator reads from it.

---

## Health Collection Schema

**Collection:** `health`

**Location:** `nomarr/persistence/database/health_ops.py`

```json
// ArangoDB document structure
{
  "_key": "worker:processing:0",     // Worker identifier (document key)
  "component": "worker:processing:0", // Worker identifier (duplicated for queries)
  "last_seen": 1737158400000,         // Unix timestamp (milliseconds) of last heartbeat
  "status": "healthy",                // Worker status (starting, healthy, stopping, crashed, failed)
  "pid": 12345,                       // Process ID (null if not running)
  "current_job": "queue/12345",       // Job document key (null if idle)
  "details_json": { ... },            // Additional metadata (embedded object)
  "restart_count": 0,                 // Number of restarts
  "last_restart": null,               // Unix timestamp of last restart
  "created_at": 1737158000000         // Unix timestamp of first registration
}
```

### Column Descriptions

**`component` (TEXT, PRIMARY KEY):**
- Unique identifier for worker
- Format: `worker:<queue_type>:<id>`
- Examples: `worker:processing:0`, `worker:processing:1`, `worker:calibration:0`
- Persists across restarts (same component ID reused)

**`last_seen` (INTEGER):**
- Unix timestamp (seconds since epoch)
- Updated every heartbeat (default: every 5 seconds)
- Used for crash detection (if `now() - last_seen > timeout`, worker is crashed)

**`status` (TEXT):**
- Current worker state
- Valid values: `starting`, `healthy`, `stopping`, `crashed`, `failed`
- State machine enforced by application logic

**`pid` (INTEGER, nullable):**
- Operating system process ID
- NULL when worker not running
- Used for process management (send signals, check if alive)

**`current_job` (INTEGER, nullable):**
- ID from `queue` table
- NULL when worker idle
- Used to track what worker is doing

**`details_json` (TEXT, nullable):**
- JSON string with additional metadata
- Typical contents:
  ```json
  {
    "queue_type": "processing",
    "batch_size": 8,
    "paused": false,
    "error_message": null
  }
  ```

**`restart_count` (INTEGER):**
- Number of times worker has been restarted
- Incremented on crash detection and restart
- Reset to 0 on manual restart
- Used for restart limiting (5 restarts in 5 minutes → permanent failure)

**`last_restart` (INTEGER, nullable):**
- Unix timestamp of last restart
- Used for sliding window restart limiting
- NULL if never restarted

**`created_at` (INTEGER):**
- Unix timestamp of first registration
- Never changes (persists across restarts)

---

## Status State Machine

### Valid States

```
starting → healthy
healthy → stopping
healthy → crashed (missed heartbeat)
stopping → (row deleted or marked as crashed)
crashed → starting (on restart)
crashed → failed (restart limit exceeded)
failed → (permanent, requires manual intervention)
```

### State Descriptions

**`starting`:**
- Worker process spawned but not yet sending heartbeats
- Transitions to `healthy` after first heartbeat
- Timeout: 30 seconds (if no heartbeat, mark as `crashed`)

**`healthy`:**
- Worker sending regular heartbeats
- Processing jobs normally
- Transitions to `stopping` on graceful shutdown
- Transitions to `crashed` if heartbeat timeout exceeded

**`stopping`:**
- Worker received SIGTERM and is shutting down gracefully
- Should finish current job and exit
- Timeout: 30 seconds (then mark as `crashed` if still present)

**`crashed`:**
- Worker stopped sending heartbeats unexpectedly
- Process may be dead or hung
- Eligible for automatic restart

**`failed`:**
- Worker exceeded restart limit (5 restarts in 5 minutes)
- Will not be restarted automatically
- Requires manual intervention (investigate, fix, manual restart)

---

## Operations

### Worker Operations (Write)

**Register (on startup):**
```python
db.health.register_worker(
    component="worker:processing:0",
    pid=os.getpid(),
    status="starting"
)
```

**Heartbeat (every 5 seconds):**
```python
db.health.update_heartbeat(
    component="worker:processing:0",
    status="healthy",
    current_job=job_id  # or None if idle
)
```

**Mark stopping (on SIGTERM):**
```python
db.health.update_status(
    component="worker:processing:0",
    status="stopping"
)
```

**Unregister (on clean exit):**
```python
db.health.remove_worker(
    component="worker:processing:0"
)
```

### Coordinator Operations (Read)

**Get all workers:**
```python
workers = db.health.get_all_workers()
for worker in workers:
    print(f"{worker['component']}: {worker['status']}")
```

**Check for crashes (every 10 seconds):**
```python
now = time.time()
timeout = 30  # seconds

workers = db.health.get_all_workers()
for worker in workers:
    if worker['status'] in ('healthy', 'starting'):
        if now - worker['last_seen'] > timeout:
            db.health.update_status(
                component=worker['component'],
                status='crashed'
            )
```

**Restart crashed worker:**
```python
worker = db.health.get_worker("worker:processing:0")
if worker['status'] == 'crashed':
    # Check restart limit
    if can_restart(worker):
        db.health.increment_restart_count(worker['component'])
        spawn_worker(worker['component'])
        db.health.update_status(
            component=worker['component'],
            status='starting',
            pid=new_pid
        )
    else:
        db.health.update_status(
            component=worker['component'],
            status='failed'
        )
```

### Pause/Resume Operations

**Pause (coordinator):**
```python
# Set paused flag in all workers' details_json
for worker in db.health.get_all_workers():
    details = json.loads(worker['details_json'] or '{}')
    details['paused'] = True
    db.health.update_details(worker['component'], json.dumps(details))
```

**Resume (coordinator):**
```python
# Clear paused flag
for worker in db.health.get_all_workers():
    details = json.loads(worker['details_json'] or '{}')
    details['paused'] = False
    db.health.update_details(worker['component'], json.dumps(details))
```

**Check paused (worker):**
```python
# Worker checks own status
worker = db.health.get_worker(self.component_id)
details = json.loads(worker['details_json'] or '{}')
if details.get('paused'):
    # Don't dequeue new jobs, finish current job
    pass
```

---

## Invariants

### 1. Unique Component IDs

**Invariant:** Each worker has a unique `component` value.

**Enforcement:** Primary key constraint on `component` column.

**Violation:** Multiple workers with same component ID.

**Prevention:**
- Workers use deterministic IDs based on queue type and index
- Coordinator ensures no duplicate IDs when spawning workers

### 2. Heartbeat Freshness

**Invariant:** `last_seen` for `healthy` workers is recent (within timeout).

**Enforcement:** Coordinator periodically checks and marks stale workers as `crashed`.

**Violation:** Worker stops sending heartbeats but not marked as crashed.

**Prevention:**
- Coordinator runs crash detection every 10 seconds
- Timeout set to 30 seconds (6 missed heartbeats → crash)

### 3. PID Validity

**Invariant:** `pid` is NULL or refers to an existing process.

**Enforcement:** Coordinator checks if process exists using `psutil.pid_exists()`.

**Violation:** PID refers to dead process.

**Prevention:**
- Coordinator checks PID validity during crash detection
- If process dead but heartbeat recent, mark as crashed

### 4. Status Transitions

**Invariant:** Status changes follow state machine rules.

**Enforcement:** Application logic in worker and coordinator.

**Violation:** Invalid state transition (e.g., `stopping` → `starting` without going through `crashed`).

**Prevention:**
- Workers only set `starting`, `healthy`, `stopping`
- Coordinator only sets `crashed`, `failed`
- No direct transitions from `stopping` to `starting`

### 5. Restart Count Accuracy

**Invariant:** `restart_count` reflects actual number of restarts.

**Enforcement:** Incremented only on crash restart, reset on manual restart.

**Violation:** Incorrect restart count.

**Prevention:**
- Only coordinator increments restart count
- Manual restart via API clears restart count
- Restart history tracked in `last_restart`

### 6. Current Job Validity

**Invariant:** `current_job` is NULL or refers to existing job in `queue` table.

**Enforcement:** Validated by application (ArangoDB uses document references, not foreign keys).

**Violation:** Current job ID doesn't exist in queue.

**Prevention:**
- Workers set `current_job` when dequeuing
- Workers clear `current_job` when job completes/fails
- Coordinator validates job IDs during status checks

---

## Concurrency

### Read-Write Pattern

**Workers (write):**
- Each worker updates only its own row
- No contention between workers
- Writes are small (single row UPDATE)

**Coordinator (read):**
- Reads all rows periodically
- No writes except during crash recovery
- Uses transactions for consistency

**Contention:** Minimal (workers write different rows, coordinator mostly reads).

### Lock Duration

**Heartbeat write:**
```python
# ~1ms
UPDATE health SET last_seen = ?, current_job = ? WHERE component = ?
```

**Crash detection read:**
```python
# ~5-10ms (depends on worker count)
SELECT * FROM health WHERE status IN ('healthy', 'starting')
```

**No lock escalation** (ArangoDB uses document-level MVCC for concurrent access).

### Race Conditions

**Scenario 1: Worker dies between heartbeat and crash detection**
- **Impact:** Detected on next crash detection cycle (10 seconds)
- **Acceptable:** 10-second delay in crash detection is fine

**Scenario 2: Worker restarts while coordinator marking as crashed**
- **Prevention:** Coordinator checks PID before marking crashed
- **Resolution:** New PID → new registration, old row cleaned up

**Scenario 3: Multiple coordinators running**
- **Impact:** Duplicate crash detection, duplicate restarts
- **Prevention:** Nomarr runs single coordinator process (design constraint)
- **Future:** Add coordinator election if multi-coordinator needed

---

## Performance

### Table Size

**Growth:** One row per worker (typically 2-4 workers).

**Size:** ~200 bytes per row × 4 workers = 800 bytes.

**No cleanup needed** (fixed row count).

### Query Performance

**Heartbeat update (hot path):**
```sql
-- Uses primary key, ~1ms
UPDATE health SET last_seen = ?, current_job = ? WHERE component = ?
```

**Crash detection (every 10s):**
```sql
-- Full table scan, but only 4 rows, ~5ms
SELECT * FROM health WHERE status IN ('healthy', 'starting')
```

**No indexes needed** (primary key sufficient).

### Write Frequency

**Per worker:**
- Heartbeat every 5 seconds = 0.2 writes/second
- Status updates occasional (start, stop, pause)

**Total:**
- 4 workers × 0.2 writes/second = 0.8 writes/second
- Negligible load

---

## Monitoring

### Health Checks

**Check all workers healthy:**
```python
def all_workers_healthy(db: Database) -> bool:
    workers = db.health.get_all_workers()
    return all(w['status'] == 'healthy' for w in workers)
```

**Check for crashed workers:**
```python
def get_crashed_workers(db: Database) -> list[str]:
    workers = db.health.get_all_workers()
    return [w['component'] for w in workers if w['status'] == 'crashed']
```

**Check for failed workers:**
```python
def get_failed_workers(db: Database) -> list[str]:
    workers = db.health.get_all_workers()
    return [w['component'] for w in workers if w['status'] == 'failed']
```

### Metrics

**Track over time:**
- Worker restart count (gauge)
- Worker crash count (counter)
- Time since last crash (gauge)
- Workers in each status (gauge)

**Alert on:**
- Any worker in `failed` status
- Restart count > 3 in 5 minutes
- All workers crashed simultaneously

---

## Debugging

### View Health Collection

```bash
# Using arangosh (inside container)
docker exec -it nomarr-arangodb arangosh \
  --server.username nomarr \
  --server.password "$(grep arango_password config/nomarr.yaml | cut -d: -f2 | tr -d ' ')" \
  --server.database nomarr \
  --javascript.execute-string 'db.health.toArray().forEach(d => print(JSON.stringify(d, null, 2)))'

# Using Python
docker exec -it nomarr python -c "
from nomarr.persistence.db import Database
db = Database()
for worker in db.health.get_all_workers():
    print(f\"{worker['component']}: {worker['status']} (PID {worker['pid']})\")
"
```

### Check Worker Process

```bash
# Check if process exists
ps aux | grep <pid>

# Check if process is zombie
ps -o stat= -p <pid>

# Send test signal (no-op)
kill -0 <pid>
```

### Force Worker Restart

```bash
# Kill worker process
kill <pid>

# Wait for crash detection (10 seconds)
# Or manually mark as crashed via arangosh
docker exec -it nomarr-arangodb arangosh \
  --server.username nomarr \
  --server.password "<password>" \
  --server.database nomarr \
  --javascript.execute-string 'db.health.update("worker:processing:0", {status: "crashed"})'
```

### Clear Failed Worker

```bash
# Reset restart count and status via arangosh
docker exec -it nomarr-arangodb arangosh \
  --server.username nomarr \
  --server.password "<password>" \
  --server.database nomarr \
  --javascript.execute-string '
    db.health.update("worker:processing:0", {
      status: "crashed",
      restart_count: 0,
      last_restart: null
    })
  '

# Coordinator will restart on next cycle
```

---

## Common Issues

### Worker Stuck in "starting"

**Symptoms:**
- Worker in `starting` status for > 30 seconds
- No heartbeat updates

**Causes:**
- Worker process failed to start (import error, missing dependency)
- Worker deadlocked during initialization

**Resolution:**
1. Check worker logs for errors
2. Check PID still exists: `ps -p <pid>`
3. If process dead, mark as crashed via arangosh: `db.health.update("<component>", {status: "crashed"})`
4. If process alive but hung, kill: `kill -9 <pid>`

### Worker Marked "crashed" But Still Running

**Symptoms:**
- Worker status is `crashed`
- Worker process still exists and appears healthy

**Causes:**
- Database writes blocked (lock timeout)
- Worker deadlocked (can't send heartbeat)
- Clock skew (worker and coordinator have different times)

**Resolution:**
1. Check worker logs for database errors
2. Check database connectivity: `docker exec -it nomarr-arangodb arangosh --server.database nomarr --javascript.execute-string 'db.queue.count()'`
3. Restart worker: `kill <pid>` (coordinator will restart)

### Restart Loop

**Symptoms:**
- Worker repeatedly crashes and restarts
- Eventually marks as `failed`

**Causes:**
- Persistent error (bad config, missing model, permission issue)
- Resource exhaustion (OOM, disk full)
- Corrupt job in queue

**Resolution:**
1. Check worker logs for crash reason
2. Fix underlying issue (config, permissions, resources)
3. Clear failed jobs: `DELETE FROM queue WHERE status = 'error';`
4. Manually restart: Use API `/api/web/worker/restart`

---

## API Integration

### Health Endpoints

**Get worker status:**
```bash
curl http://localhost:8888/api/web/worker/status
```

Response:
```json
[
  {
    "component": "worker:processing:0",
    "status": "healthy",
    "pid": 12345,
    "current_job": 67890,
    "restart_count": 0,
    "last_seen": 1733407200
  }
]
```

**Restart workers:**
```bash
curl -X POST http://localhost:8888/api/web/worker/restart
```

See [../user/api_reference.md](../user/api_reference.md) for full API documentation.

---

## Schema Migration

### Adding Columns

**If adding non-critical column:**
```sql
-- Safe to add with default value
ALTER TABLE health ADD COLUMN new_field TEXT DEFAULT '';
```

**If adding critical column:**
- Stop all workers
- Add column with migration script
- Restart workers

**Pre-alpha:** No backward compatibility needed. Can drop and recreate table.

---

## Related Documentation

- [Workers](workers.md) - Worker process lifecycle
- [Services](services.md) - ProcessingService and worker management
- [Architecture](architecture.md) - System design
- [API Reference](../user/api_reference.md) - Worker API endpoints

---

## Summary

**Health table purpose:**
- Track worker liveness via heartbeats
- Detect crashes via timeout
- Coordinate pause/resume operations
- Track restart history

**Key points:**
- One row per worker (2-4 total)
- Workers write own row, coordinator reads all
- 5-second heartbeat, 30-second timeout
- State machine enforced by application
- Minimal contention, high performance
