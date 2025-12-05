# Queue System Reference

**Queue Normalization, DTOs, and Processing Flow**

---

## Overview

Nomarr uses a **single normalized queue table** for all job types (processing, calibration). This design provides:

- Unified job management (single API for all job types)
- Type safety via `queue_type` enum
- Efficient querying with composite indexes
- Atomic status transitions

**Key principle:** One table, multiple queue types, strict status transitions.

---

## Queue Table Schema

**Table:** `queue`

**Location:** `nomarr/persistence/database/schema.sql`

```sql
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    queue_type TEXT NOT NULL DEFAULT 'processing',
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    results_json TEXT,
    enqueued_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(queue_type, status, priority DESC, enqueued_at ASC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_path_type ON queue(path, queue_type, status) WHERE status IN ('pending', 'running');
```

### Column Descriptions

**`id` (INTEGER, PRIMARY KEY):**
- Auto-incrementing job ID
- Unique across all queue types
- Used for job tracking and references

**`library_id` (INTEGER):**
- Foreign key to `libraries` table
- Tracks which library this file belongs to
- Used for library-scoped operations (clear library jobs, get library stats)

**`path` (TEXT):**
- Absolute path to audio file
- Must be readable by worker processes
- Used as job payload (what to process)

**`queue_type` (TEXT):**
- Type of queue: `processing` or `calibration`
- Determines which worker handles the job
- Default: `processing`

**`status` (TEXT):**
- Current job state: `pending`, `running`, `completed`, `error`
- Determines job eligibility for dequeue
- Indexed for fast querying

**`priority` (INTEGER):**
- Job priority (higher = more important)
- Default: 0
- Used for queue ordering (high priority first)

**`error` (TEXT, nullable):**
- Error message if job failed
- NULL if no error
- Displayed in UI and API

**`results_json` (TEXT, nullable):**
- JSON string with job results
- Structure depends on queue type:
  - Processing: `{"tags": [...], "embeddings": [...], "duration": 123.45}`
  - Calibration: `{"calibrated_tags": 42, "thresholds": {...}}`

**`enqueued_at` (INTEGER):**
- Unix timestamp when job was created
- Used for queue ordering and age calculation

**`started_at` (INTEGER, nullable):**
- Unix timestamp when job started running
- NULL if not yet started
- Used for processing time calculation

**`completed_at` (INTEGER, nullable):**
- Unix timestamp when job finished (success or error)
- NULL if not yet completed
- Used for processing time calculation

### Indexes

**`idx_queue_status` (Composite):**
```sql
CREATE INDEX idx_queue_status ON queue(queue_type, status, priority DESC, enqueued_at ASC);
```

**Purpose:** Fast dequeue (find next `pending` job).

**Query:**
```sql
SELECT * FROM queue
WHERE queue_type = ? AND status = 'pending'
ORDER BY priority DESC, enqueued_at ASC
LIMIT 1;
```

**Performance:** O(log N) lookup, O(1) dequeue.

**`idx_queue_path_type` (Unique Partial):**
```sql
CREATE UNIQUE INDEX idx_queue_path_type ON queue(path, queue_type, status)
WHERE status IN ('pending', 'running');
```

**Purpose:** Prevent duplicate jobs for same file (per queue type).

**Enforcement:** Can't enqueue same path twice if already pending or running.

**Allows:** Same path in multiple queue types or after completion.

---

## Queue Types

### Processing Queue

**Purpose:** Audio analysis (embeddings + tagging).

**Queue Type:** `processing`

**Job Payload:**
- Input: `path` (audio file)
- Output: `results_json` with tags and embeddings

**Workers:** Configured by `processing.workers` in config.

**Typical size:** 100-10,000 jobs during library scan.

### Calibration Queue

**Purpose:** Tag threshold calculation.

**Queue Type:** `calibration`

**Job Payload:**
- Input: `path` (processed audio file)
- Output: `results_json` with calibration data

**Workers:** Configured by `processing.calibration_workers` in config (default: 1).

**Typical size:** 1-100 jobs during calibration.

### Future Queue Types

**Design supports adding:**
- `tagging` - Re-tag without re-embedding
- `export` - Export to file formats
- `sync` - Sync with external systems

**Pattern:** Add queue type, spawn workers, same queue operations.

---

## Status State Machine

### Valid States

```
pending → running → completed
pending → running → error
error → pending (retry)
completed → (terminal, can be cleared)
```

### Status Descriptions

**`pending`:**
- Job waiting to be processed
- Eligible for dequeue by workers
- Initial state for new jobs

**`running`:**
- Job currently being processed by a worker
- Not eligible for dequeue
- Should transition to `completed` or `error` within timeout

**`completed`:**
- Job finished successfully
- Results in `results_json`
- Terminal state (not processed again)

**`error`:**
- Job failed
- Error message in `error` column
- Can be retried (status → `pending`)

### State Transitions

**Enqueue (API/Service):**
```python
INSERT INTO queue (library_id, path, queue_type, status, enqueued_at)
VALUES (?, ?, ?, 'pending', ?);
```

**Dequeue (Worker):**
```python
UPDATE queue SET status = 'running', started_at = ?
WHERE id = (
    SELECT id FROM queue
    WHERE queue_type = ? AND status = 'pending'
    ORDER BY priority DESC, enqueued_at ASC
    LIMIT 1
)
RETURNING *;
```

**Complete (Worker):**
```python
UPDATE queue SET status = 'completed', completed_at = ?, results_json = ?
WHERE id = ?;
```

**Fail (Worker):**
```python
UPDATE queue SET status = 'error', completed_at = ?, error = ?
WHERE id = ?;
```

**Retry (API/Service):**
```python
UPDATE queue SET status = 'pending', error = NULL, started_at = NULL, completed_at = NULL
WHERE id = ?;
```

---

## DTOs

### QueueStatusDict

**Purpose:** Overall queue statistics.

**Location:** `helpers/dto/queue.py`

```python
class QueueStatusDict(TypedDict):
    """Overall queue status."""
    pending: int      # Jobs waiting
    running: int      # Jobs in progress
    completed: int    # Jobs finished successfully
    errors: int       # Jobs failed
```

**Usage:**
```python
status = queue_service.get_queue_status()
print(f"Pending: {status['pending']}, Running: {status['running']}")
```

**API:** `GET /api/web/queue/queue-depth`

### JobDict

**Purpose:** Single job details.

**Location:** `helpers/dto/queue.py`

```python
class JobDict(TypedDict):
    """Single queue job."""
    id: int
    library_id: int
    path: str
    queue_type: str
    status: str
    priority: int
    error: str | None
    results_json: str | None
    enqueued_at: int
    started_at: int | None
    completed_at: int | None
```

**Usage:**
```python
job = queue_service.get_job(job_id)
if job['status'] == 'error':
    print(f"Error: {job['error']}")
```

**API:** `GET /api/web/queue/list`

### QueueDepthDict

**Purpose:** Per-status counts.

**Location:** `helpers/dto/queue.py`

```python
class QueueDepthDict(TypedDict):
    """Queue depth per status."""
    pending: int
    running: int
    completed: int
    errors: int
```

**Usage:**
```python
depth = queue_service.get_queue_depth()
print(f"Total jobs: {sum(depth.values())}")
```

**Note:** Same structure as QueueStatusDict (historical reasons).

---

## Processing Flow

### 1. Enqueue

**Trigger:** Library scan, manual enqueue, Lidarr webhook.

**Flow:**
```
scan_library()
    ↓
find_audio_files()
    ↓
for each file:
    queue_service.enqueue_file(path, library_id)
```

**Database:**
```sql
INSERT INTO queue (library_id, path, queue_type, status, enqueued_at)
VALUES (1, '/music/track.flac', 'processing', 'pending', 1733407200);
```

**Result:** Job ID returned, job in `pending` status.

### 2. Dequeue

**Trigger:** Worker loop (continuous polling).

**Flow:**
```
while not paused:
    job = queue_service.dequeue(queue_type)
    if job:
        process_job(job)
    else:
        sleep(1)
```

**Database (atomic):**
```sql
UPDATE queue SET status = 'running', started_at = 1733407205
WHERE id = (
    SELECT id FROM queue
    WHERE queue_type = 'processing' AND status = 'pending'
    ORDER BY priority DESC, enqueued_at ASC
    LIMIT 1
)
RETURNING *;
```

**Concurrency:** Multiple workers can dequeue simultaneously (atomic UPDATE prevents duplicates).

### 3. Process

**Flow:**
```
process_job(job):
    try:
        results = process_file_workflow(job['path'])
        queue_service.complete_job(job['id'], results)
    except Exception as e:
        queue_service.fail_job(job['id'], str(e))
```

**Worker logic:** See [workers.md](workers.md) for details.

### 4. Complete or Fail

**Success:**
```sql
UPDATE queue 
SET status = 'completed', completed_at = 1733407305, results_json = '{...}'
WHERE id = 123;
```

**Failure:**
```sql
UPDATE queue
SET status = 'error', completed_at = 1733407305, error = 'File not found'
WHERE id = 123;
```

**Result:** Job terminal (no further processing unless retried).

### 5. Clear or Retry

**Clear completed (API):**
```sql
DELETE FROM queue WHERE status = 'completed' AND queue_type = 'processing';
```

**Retry errors (API):**
```sql
UPDATE queue
SET status = 'pending', error = NULL, started_at = NULL, completed_at = NULL
WHERE status = 'error' AND queue_type = 'processing';
```

---

## Queue Operations

### Enqueue Operations

**Single file:**
```python
job_id = db.queue.enqueue(
    library_id=1,
    path="/music/track.flac",
    queue_type="processing"
)
```

**Batch enqueue:**
```python
job_ids = db.queue.enqueue_batch(
    library_id=1,
    paths=["/music/track1.flac", "/music/track2.flac"],
    queue_type="processing"
)
```

**Priority enqueue:**
```python
job_id = db.queue.enqueue(
    library_id=1,
    path="/music/important.flac",
    queue_type="processing",
    priority=10  # Higher priority
)
```

### Dequeue Operations

**Dequeue next job:**
```python
job = db.queue.dequeue(queue_type="processing")
if job:
    print(f"Processing {job['path']}")
```

**Atomic:** Uses UPDATE ... RETURNING to prevent race conditions.

**Returns:** `JobDict` or `None` if queue empty.

### Status Operations

**Get counts:**
```python
status = db.queue.get_status()
print(f"Pending: {status['pending']}")
```

**List jobs:**
```python
jobs = db.queue.list_jobs(
    status="error",
    queue_type="processing",
    limit=100
)
```

**Get single job:**
```python
job = db.queue.get_job(job_id=123)
if job:
    print(f"Status: {job['status']}")
```

### Completion Operations

**Mark completed:**
```python
db.queue.complete_job(
    job_id=123,
    results={"tags": [...], "duration": 234.5}
)
```

**Mark failed:**
```python
db.queue.fail_job(
    job_id=123,
    error="File not readable"
)
```

### Management Operations

**Clear completed:**
```python
cleared = db.queue.clear_completed(queue_type="processing")
print(f"Cleared {cleared} jobs")
```

**Clear errors:**
```python
cleared = db.queue.clear_errors(queue_type="processing")
print(f"Cleared {cleared} failed jobs")
```

**Retry errors:**
```python
retried = db.queue.retry_errors(queue_type="processing")
print(f"Requeued {retried} jobs")
```

**Requeue specific job:**
```python
success = db.queue.requeue_job(job_id=123)
```

---

## Concurrency

### Multiple Workers Dequeuing

**Scenario:** 2 workers call `dequeue()` simultaneously.

**Safety:** SQLite atomic UPDATE ensures each worker gets different job.

**Mechanism:**
```sql
-- Worker 1 and Worker 2 both execute:
UPDATE queue SET status = 'running' WHERE id = (SELECT id ... LIMIT 1) RETURNING *;

-- SQLite serializes updates:
-- Worker 1 gets job ID 100
-- Worker 2 gets job ID 101 (next pending job)
```

**No duplicates:** Impossible for two workers to get same job.

### Job Timeout

**Problem:** Worker crashes while processing, job stuck in `running` status.

**Solution:** Coordinator periodically checks for stale jobs:

```python
# Every 60 seconds
timeout = 300  # 5 minutes
now = time.time()

stale_jobs = db.queue.get_stale_jobs(timeout)
for job in stale_jobs:
    db.queue.fail_job(
        job_id=job['id'],
        error=f"Timeout after {timeout}s"
    )
```

**Query:**
```sql
SELECT * FROM queue
WHERE status = 'running'
  AND started_at < (strftime('%s', 'now') - ?)
```

### Database Locks

**Read operations:** Non-blocking (SQLite WAL mode).

**Write operations:** Brief exclusive lock (~1ms).

**Contention:** Low (workers write different rows).

**Optimization:** WAL mode enables concurrent reads during writes.

---

## Performance

### Dequeue Performance

**Index usage:**
```sql
-- Uses idx_queue_status
SELECT id FROM queue
WHERE queue_type = 'processing' AND status = 'pending'
ORDER BY priority DESC, enqueued_at ASC
LIMIT 1;
```

**Complexity:** O(log N) with index.

**Benchmark (10,000 jobs):**
- Cold: ~5ms
- Hot: ~1ms

### Enqueue Performance

**Single enqueue:**
```sql
-- Uses idx_queue_path_type for duplicate check
INSERT INTO queue (...) VALUES (...);
```

**Complexity:** O(log N) with index.

**Benchmark:**
- Single: ~2ms
- Batch (100): ~50ms (0.5ms per job)

### Status Query Performance

**Get counts:**
```sql
-- Uses idx_queue_status
SELECT queue_type, status, COUNT(*) FROM queue
GROUP BY queue_type, status;
```

**Complexity:** O(N) table scan, but N is small (< 10,000).

**Benchmark (10,000 jobs):** ~20ms

**Optimization:** Materialize counts in separate table if needed (future).

---

## Error Handling

### Common Errors

**1. File Not Found:**
```python
# Worker
try:
    process_file(job['path'])
except FileNotFoundError:
    db.queue.fail_job(job['id'], f"File not found: {job['path']}")
```

**2. Permission Denied:**
```python
except PermissionError:
    db.queue.fail_job(job['id'], f"Permission denied: {job['path']}")
```

**3. Invalid Audio:**
```python
except AudioDecodeError as e:
    db.queue.fail_job(job['id'], f"Invalid audio: {e}")
```

**4. Model Error:**
```python
except ModelError as e:
    db.queue.fail_job(job['id'], f"Model error: {e}")
```

**5. Timeout:**
```python
# Coordinator
if job_runtime > timeout:
    db.queue.fail_job(job['id'], f"Timeout after {timeout}s")
```

### Retry Strategy

**Automatic retry:** Not implemented (by design).

**Manual retry:** Via API (`POST /api/web/queue/retry-errors`).

**Reasoning:**
- Most errors are persistent (file not found, invalid audio)
- Automatic retry wastes resources
- User can inspect errors and fix before retrying

**Future:** Add retry count and exponential backoff for transient errors.

---

## Monitoring

### Queue Health Metrics

**Track:**
- Queue depth per status (gauge)
- Enqueue rate (counter)
- Dequeue rate (counter)
- Processing time per job (histogram)
- Error rate (counter)

**Alerts:**
- Queue depth > 10,000 (slow processing)
- Error rate > 10% (configuration issue)
- No dequeue activity for 60s (workers stopped)

### Queue Statistics API

```bash
curl http://localhost:8888/api/web/queue/queue-depth
```

Response:
```json
{
  "pending": 1234,
  "running": 2,
  "completed": 5678,
  "errors": 42
}
```

See [../user/api_reference.md](../user/api_reference.md) for full API.

---

## Database Maintenance

### Clear Old Jobs

**Completed jobs accumulate over time:**

```sql
-- Delete completed jobs older than 30 days
DELETE FROM queue
WHERE status = 'completed'
  AND completed_at < (strftime('%s', 'now') - 2592000);
```

**Schedule:** Weekly or monthly.

**Consideration:** Keep some history for analytics.

### Vacuum Database

**After large deletes:**

```bash
sqlite3 /data/nomarr.db "VACUUM;"
```

**Reclaims:** Disk space from deleted rows.

**Frequency:** Monthly or after clearing 10,000+ jobs.

---

## Debugging

### View Queue State

```bash
# SQLite CLI
sqlite3 /data/nomarr.db "
SELECT queue_type, status, COUNT(*) 
FROM queue 
GROUP BY queue_type, status;
"
```

### Find Stuck Jobs

```bash
# Jobs running for > 10 minutes
sqlite3 /data/nomarr.db "
SELECT id, path, started_at, (strftime('%s', 'now') - started_at) as runtime_s
FROM queue
WHERE status = 'running'
  AND started_at < (strftime('%s', 'now') - 600)
ORDER BY runtime_s DESC;
"
```

### Inspect Failed Job

```bash
# Get error message
sqlite3 /data/nomarr.db "
SELECT id, path, error
FROM queue
WHERE id = 123;
"
```

### Manually Fix Job

```bash
# Retry specific job
sqlite3 /data/nomarr.db "
UPDATE queue
SET status = 'pending', error = NULL, started_at = NULL, completed_at = NULL
WHERE id = 123;
"
```

---

## Migration Considerations

### Schema Changes

**Adding columns:**
```sql
-- Safe with default value
ALTER TABLE queue ADD COLUMN retry_count INTEGER DEFAULT 0;
```

**Adding indexes:**
```sql
-- Safe, but may take time with large queue
CREATE INDEX idx_queue_library ON queue(library_id, status);
```

**Changing constraints:**
- Requires recreate table (SQLite limitation)
- Stop workers, migrate, restart

**Pre-alpha:** No backward compatibility needed. Can drop and recreate.

### Data Migration

**Moving from old schema:**
```sql
-- Example: Migrate from old separate tables
INSERT INTO queue (library_id, path, queue_type, status, enqueued_at)
SELECT library_id, path, 'processing', 'pending', created_at
FROM old_processing_queue;
```

---

## Related Documentation

- [Workers](workers.md) - Worker processing loop
- [Health](health.md) - Worker health monitoring
- [Services](services.md) - QueueService API
- [Architecture](architecture.md) - System design
- [API Reference](../user/api_reference.md) - Queue API endpoints

---

## Summary

**Queue design:**
- Single normalized table for all job types
- Type-safe with `queue_type` enum
- Strict status state machine
- Atomic dequeue prevents duplicates
- Indexed for fast operations

**Key operations:**
- Enqueue: Add jobs to queue
- Dequeue: Claim next job (atomic)
- Complete/Fail: Mark job terminal
- Retry: Reset failed jobs to pending
- Clear: Remove terminal jobs

**Concurrency:**
- Multiple workers dequeue safely
- Atomic UPDATE ensures no duplicates
- Low contention (workers write different rows)
- WAL mode enables concurrent reads

**Performance:**
- O(log N) dequeue with index
- O(1) status update
- ~1-5ms per operation
- Scales to 10,000+ jobs
