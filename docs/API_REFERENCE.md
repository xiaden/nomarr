# API Endpoints Reference

## Authentication

All endpoints (except `/api/v1/info` for public health checks) require Bearer token authentication:

```bash
Authorization: Bearer <API_KEY>
```

Get/generate API key inside container:

```bash
docker exec nomarr python3 -m nomarr.manage_key --show
docker exec nomarr python3 -m nomarr.manage_key --generate
```

---

## Core Endpoints (Lidarr Integration)

### POST /api/v1/tag

Enqueue a file for tagging. Returns immediately (non-blocking) or waits for completion (blocking mode).

**Request:**

```json
{
  "path": "/music/Artist/Album/Track.mp3",
  "force": false
}
```

**Response (non-blocking):**

```json
{
  "job_id": 123,
  "status": "queued",
  "blocking": false
}
```

**Response (blocking mode, on completion):**

```json
{
  "job_id": 123,
  "status": "done",
  "path": "/music/Artist/Album/Track.mp3",
  "created_at": "2025-10-26T12:00:00",
  "started_at": "2025-10-26T12:00:01",
  "finished_at": "2025-10-26T12:00:15",
  "error": null,
  "blocking": true
}
```

**Lidarr Custom Script Example:**

```bash
#!/bin/bash
# Save as /config/scripts/autotag.sh in Lidarr container

API_KEY="your-api-key-here"
FILE_PATH="$lidarr_trackfile_path"  # Lidarr env variable

curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$FILE_PATH\",\"force\":true}" \
  http://autotag:8356/api/v1/tag
```

---

### GET /api/v1/queue

List recent jobs with summary (legacy endpoint for backward compatibility).

**Note:** Use `/list` for pagination and filtering support.

Query params: `limit` (default 5 if omitted or 25)

Response:

```json
{
  "summary": {"pending": 0, "running": 0, "done": 10, "error": 1},
  "jobs": [
    {"job_id":123, "status":"done", "path":"/music/Track.mp3", "created_at": ..., "started_at": ..., "finished_at": ..., "error": null}
  ],
  "limit": 5
}
```

---

### GET /api/v1/list

List jobs with pagination and optional status filtering.

**Query Parameters:**

- `limit` (int, default: 50) - Maximum number of jobs to return
- `offset` (int, default: 0) - Number of jobs to skip (for pagination)
- `status` (string, optional) - Filter by status: `pending`, `running`, `done`, or `error`

**Examples:**

```bash
# Get first 50 jobs
GET /api/v1/list

# Get next 50 jobs (page 2)
GET /api/v1/list?limit=50&offset=50

# Get only pending jobs
GET /api/v1/list?status=pending

# Get 100 error jobs, starting from job 200
GET /api/v1/list?limit=100&offset=200&status=error
```

**Response:**

```json
{
  "total": 1234,
  "jobs": [
    {
      "job_id": 123,
      "status": "done",
      "path": "/music/Artist/Album/Track.mp3",
      "created_at": 1698518400000,
      "started_at": 1698518401000,
      "finished_at": 1698518415000,
      "error": null
    }
  ],
  "counts": {
    "pending": 10,
    "running": 1,
    "done": 1220,
    "error": 3
  },
  "limit": 50,
  "offset": 0
}
```

**Notes:**

- `total` reflects the count matching the status filter (or all jobs if no filter)
- `counts` always shows totals for all statuses regardless of filter
- Timestamps are in milliseconds since epoch
- Jobs are ordered by ID descending (newest first)

---

### GET /api/v1/status/{job_id}

Get status of a specific job.

**Response:**

```json
{
  "job_id": 123,
  "status": "done",
  "path": "/music/Artist/Album/Track.mp3",
  "created_at": "2025-10-26T12:00:00",
  "started_at": "2025-10-26T12:00:01",
  "finished_at": "2025-10-26T12:00:15",
  "error": null
}
```

**Status values:** `pending`, `running`, `done`, `error`

---

### GET /api/v1/info

Comprehensive system info: config, models, queue, worker state.

**Response:**

```json
{
  "config": {
    "db_path": "/app/config/db/essentia.sqlite",
    "models_dir": "/app/models",
    "namespace": "essentia",
    "api_host": "0.0.0.0",
    "api_port": 8356,
    "worker_enabled": true,
    "worker_enabled_default": true,
    "poll_interval": 2,
    "blocking_mode": true,
    "blocking_timeout": 3600
  },
  "models": {
    "total_heads": 17,
    "embeddings": ["effnet", "vggish", "yamnet"]
  },
  "queue": {
    "depth": 11,
    "counts": {
      "pending": 10,
      "running": 1,
      "done": 5420,
      "error": 3
    }
  },
  "worker": {
    "enabled": true,
    "alive": true,
    "last_heartbeat": "2025-10-26T12:05:30"
  }
}
```

---

## Admin Endpoints

### POST /admin/queue/remove

Remove a non-running job. Auto-resumes worker.

**Request:**

```json
{
  "job_id": 123
}
```

**Response:**

```json
{
  "status": "ok",
  "removed": 123,
  "worker_enabled": true
}
```

---

### POST /admin/queue/flush

Flush jobs by status (default: pending + error). Auto-resumes worker.

**Request:**

```json
{
  "statuses": ["pending", "error", "done"]
}
```

**Response:**

```json
{
  "status": "ok",
  "flushed_statuses": ["pending", "error", "done"],
  "worker_enabled": true
}
```

---

### POST /admin/queue/cleanup

Remove old finished jobs (done/error older than N hours).

**Request:**

```json
{
  "max_age_hours": 168
}
```

Or use query param: `POST /admin/queue/cleanup?max_age_hours=168`

**Response:**

```json
{
  "status": "ok",
  "max_age_hours": 168,
  "jobs_removed": 42
}
```

---

#### POST /admin/cache/refresh

Rebuild the in-memory predictor cache now (discover heads, load missing, drop stale on access). Use after adding/removing models.

Response:

```json
{ "status": "ok", "predictors": 17 }
```

### POST /admin/worker/pause

Disable the background worker (stops processing queue).

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": false
}
```

---

### POST /admin/worker/resume

Enable the background worker (resumes queue processing).

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": true
}
```

---

### POST /admin/calibration/run

Generate calibration from all library files with drift tracking. Requires `calibrate_heads: true` in config (returns 403 otherwise).

**Request:** Empty body

**Response:**

```json
{
  "version": 3,
  "heads_processed": 17,
  "stable_heads": 12,
  "unstable_heads": 5,
  "heads": [
    {
      "model_name": "effnet",
      "head_name": "mood_happy",
      "version": 3,
      "file_count": 3500,
      "is_stable": false,
      "drift": {
        "apd_p5": 0.023,
        "apd_p95": 0.015,
        "srd": 0.067,
        "jsd": 0.142,
        "median_drift": 0.031,
        "iqr_drift": 0.089
      },
      "reference_updated": true
    }
  ]
}
```

See [CALIBRATION.md](CALIBRATION.md) for drift metrics interpretation.

---

### GET /admin/calibration/history

Query calibration run history. Requires `calibrate_heads: true`.

**Query Parameters:**
- `model`: Filter by model name (optional)
- `head`: Filter by head name (optional)
- `limit`: Max results (default: 50)

**Example:** `GET /admin/calibration/history?model=effnet&head=mood_happy&limit=10`

**Response:**

```json
{
  "runs": [
    {
      "id": 42,
      "model_name": "effnet",
      "head_name": "mood_happy",
      "version": 3,
      "file_count": 3500,
      "timestamp": 1704067200.0,
      "p5": 0.12,
      "p95": 0.89,
      "range": 0.77,
      "reference_version": 2,
      "is_stable": false,
      "drift": {
        "apd_p5": 0.023,
        "apd_p95": 0.015,
        "srd": 0.067,
        "jsd": 0.142,
        "median_drift": 0.031,
        "iqr_drift": 0.089
      }
    }
  ]
}
```

---

### POST /admin/calibration/retag-all

Bulk enqueue all tagged files for re-tagging with final stable calibration. Requires `calibrate_heads: true`.

**Request:** Empty body

**Response:**

```json
{
  "enqueued": 8423,
  "message": "Enqueued 8423 tagged files for re-tagging"
}
```

**Use case:** After iterative calibration refinement, use this to apply final stable calibration to entire library.

---

## Unified Schema Summary

All endpoints now return consistent structures matching the CLI output:

**Job Object:**

```json
{
  "job_id": 123,
  "status": "done|pending|running|error",
  "path": "/absolute/path/to/file.mp3",
  "created_at": "ISO8601 timestamp",
  "started_at": "ISO8601 timestamp or null",
  "finished_at": "ISO8601 timestamp or null",
  "error": "error message or null"
}
```

**Queue Summary:**

```json
{
  "pending": 10,
  "running": 1,
  "done": 5420,
  "error": 3
}
```

**Config Section:**

```json
{
  "db_path": "...",
  "models_dir": "...",
  "namespace": "essentia",
  "worker_enabled": true,
  "blocking_mode": true,
  "blocking_timeout": 3600
}
```

**Models Section:**

```json
{
  "total_heads": 17,
  "embeddings": ["effnet", "vggish", "yamnet"]
}
```

---

## Lidarr Integration Patterns

### On Import Hook (recommended)

Use Lidarr's **On Import** custom script to tag files immediately after import:

1. **Lidarr Settings** → **Connect** → **Add Custom Script**
2. **Triggers:** On Import, On Upgrade, On Retag
3. **Script Path:** `/path/to/autotag-hook.sh`

**Script Template:**

```bash
#!/bin/bash
# /config/scripts/lidarr-autotag-hook.sh

API_KEY="YOUR_API_KEY_HERE"
AUTOTAG_URL="http://autotag:8356"

# Lidarr provides these environment variables on import/upgrade/retag
FILE_PATH="$lidarr_trackfile_path"

if [ -z "$FILE_PATH" ]; then
  echo "No file path provided by Lidarr"
  exit 1
fi

echo "Tagging: $FILE_PATH"

# Call autotag API (force=true to overwrite existing tags)
RESPONSE=$(curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$FILE_PATH\",\"force\":true}" \
  "$AUTOTAG_URL/tag")

echo "Response: $RESPONSE"

# Optional: check for job_id in response
JOB_ID=$(echo "$RESPONSE" | grep -o '"job_id":[0-9]*' | grep -o '[0-9]*')
if [ -n "$JOB_ID" ]; then
  echo "Queued as job $JOB_ID"
else
  echo "Warning: No job_id in response"
fi
```

### Polling Pattern (for non-blocking mode)

If you set `blocking_mode: false` in config:

```bash
#!/bin/bash
API_KEY="YOUR_KEY"
AUTOTAG_URL="http://autotag:8356"
FILE_PATH="$lidarr_trackfile_path"

# Enqueue
RESPONSE=$(curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$FILE_PATH\",\"force\":true}" \
  "$AUTOTAG_URL/tag")

JOB_ID=$(echo "$RESPONSE" | grep -o '"job_id":[0-9]*' | grep -o '[0-9]*')

# Poll for completion (optional, not recommended for Lidarr)
for i in {1..30}; do
  STATUS=$(curl -s -H "Authorization: Bearer $API_KEY" \
    "$AUTOTAG_URL/status/$JOB_ID" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

  if [ "$STATUS" = "done" ] || [ "$STATUS" = "error" ]; then
    echo "Job $JOB_ID finished with status: $STATUS"
    break
  fi
  sleep 2
done
```

**Recommendation for Lidarr:** Use **blocking mode** (`blocking_mode: true` in config) so the script waits for tagging to complete before returning. This ensures Lidarr's post-processing doesn't race with tagging.

---

## Configuration for Lidarr Use Case

**Recommended `config/config.yaml` for Lidarr:**

```yaml
paths:
  models_dir: /app/models
  db_path: /app/config/db/essentia.sqlite

tagger:
  namespace: essentia
  overwrite_tags: true # Allow retagging on upgrades

api:
  host: 0.0.0.0
  port: 8356
  blocking_mode: true # Wait for completion (important for Lidarr hooks)
  blocking_timeout: 600 # 10 min timeout per file

worker:
  enabled: true
  poll_interval: 2

cleanup_age_hours: 168 # Auto-cleanup old jobs after 7 days
```

**Docker Compose Volume Mapping:**

```yaml
services:
  autotag:
    volumes:
      - /path/to/music:/music # SAME path as Lidarr uses
      - ./config:/app/config
      # Optional: Custom models (only if not using packaged models)
      # - ./models:/app/models
```

**Note:** The `models` directory is **optional**. The Docker image includes pre-trained Essentia models. Only map a custom models directory if you want to use your own TensorFlow models.

**Critical:** The music library must be mounted at the **same absolute path** in both Lidarr and autotag containers. If Lidarr sees `/music/Album/Track.mp3`, autotag must also see `/music/Album/Track.mp3`.

---

## Web UI Endpoints

The web UI provides a browser-based interface for monitoring and controlling the tagging system. All web endpoints use session-based authentication.

**Authentication:** Session token (obtained via login) sent as Bearer token.

**Base URL:** `http://<server>:8356/web/`

### Authentication Endpoints

#### POST /web/auth/login

Authenticate with admin password and receive session token.

**Request:**

```json
{
  "password": "your_admin_password"
}
```

**Response (success):**

```json
{
  "token": "abc123def456...",
  "expires_in": 86400
}
```

**Response (failure):**

```json
{
  "detail": "Invalid password"
}
```

**Session lifetime:** 24 hours (86400 seconds)

#### POST /web/auth/logout

Invalidate current session token.

**Headers:**

```
Authorization: Bearer <session_token>
```

**Response:**

```json
{
  "status": "ok"
}
```

### Processing Endpoints

All processing endpoints require session authentication.

#### POST /web/api/process

Process a single file with SSE streaming progress (same as `/internal/process_stream`).

**Request:**

```json
{
  "path": "/music/Track.mp3",
  "force": false
}
```

**Response:** SSE stream (see Internal Endpoints for event format)

#### POST /web/api/batch-process

Process multiple files synchronously (same as `/internal/batch_process`).

**Request:**

```json
{
  "paths": ["/music/Track1.mp3", "/music/Track2.mp3"],
  "force": false
}
```

**Response:**

```json
{
  "results": [
    { "path": "/music/Track1.mp3", "tags_written": 42, "duration": 3.5 },
    { "path": "/music/Track2.mp3", "tags_written": 38, "duration": 3.2 }
  ]
}
```

### Queue Management Endpoints

#### GET /web/api/list

List jobs with pagination and filtering (proxies public `/list` endpoint).

**Query Parameters:**

- `limit` (int, default: 50)
- `offset` (int, default: 0)
- `status` (string, optional): `pending`, `running`, `done`, `error`

**Response:** Same as public `/list` endpoint

#### GET /web/api/queue

Get queue summary (proxies public `/queue` endpoint).

**Query Parameters:**

- `limit` (int, default: 5)

**Response:** Same as public `/queue` endpoint

#### GET /web/api/status/{job_id}

Get status of specific job (proxies public `/status/{job_id}`).

**Response:** Same as public `/status/{job_id}` endpoint

#### POST /web/api/queue/remove

Remove a job from queue (proxies public `/admin/queue/remove`).

**Request:**

```json
{
  "job_id": 123
}
```

**Response:**

```json
{
  "status": "ok",
  "removed": 123,
  "worker_enabled": true
}
```

#### POST /web/api/queue/flush

Flush jobs by status (proxies public `/admin/queue/flush`).

**Request:**

```json
{
  "statuses": ["pending", "error"]
}
```

**Response:**

```json
{
  "status": "ok",
  "flushed_statuses": ["pending", "error"],
  "worker_enabled": true
}
```

#### POST /web/api/queue/cleanup

Remove old finished jobs (proxies public `/admin/queue/cleanup`).

**Request:**

```json
{
  "max_age_hours": 168
}
```

**Response:**

```json
{
  "status": "ok",
  "max_age_hours": 168,
  "jobs_removed": 42
}
```

#### POST /web/api/queue/reset-stuck

Reset jobs stuck in "running" state to "pending".

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "reset_count": 3
}
```

### Admin Endpoints

#### POST /web/api/admin/worker/pause

Pause the background worker (proxies public `/admin/worker/pause`).

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": false
}
```

#### POST /web/api/admin/worker/resume

Resume the background worker (proxies public `/admin/worker/resume`).

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": true
}
```

#### POST /web/api/admin/cache/refresh

Refresh predictor cache (proxies public `/admin/cache/refresh`).

**Response:**

```json
{
  "status": "ok",
  "predictors": 17
}
```

### Utility Endpoints

#### GET /web/api/info

Get system information (proxies public `/info`).

**Response:** Same as public `/info` endpoint

#### GET /web/api/health

Get cache and worker status (proxies internal `/internal/health`).

**Response:**

```json
{
  "cache_initialized": true,
  "worker_count": 4,
  "available_workers": 2
}
```

### Admin Password Management

The admin password is managed via CLI (`manage_password.py`) and stored as a salted SHA-256 hash in the database.

**View current password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --show
```

**Verify a password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --verify
```

**Reset password (prompts twice):**

```bash
docker exec nomarr python3 -m nomarr.manage_password --reset
```

**Set password in config:**

```yaml
# config/config.yaml
admin_password: your_secure_password
```

**Retrieve auto-generated password from logs:**

```bash
docker compose logs nomarr | grep "Admin password"
```

---

## CLI Architecture

The CLI accesses Application services directly (no HTTP endpoints). Commands like `nom run`, `nom list`, and `nom remove` work entirely within the same Python process that runs the API server.

**Benefits:**

- No HTTP overhead or authentication needed
- Direct access to model cache and services
- Instant execution with no network latency
- Real-time progress via Rich terminal UI

**Worker Management:**

- Application uses ProcessingCoordinator with configurable `worker_count` (default 1)
- Each worker process loads independent model cache (~400MB RAM)
- GPU-enabled workers run concurrently via `TF_FORCE_GPU_ALLOW_GROWTH=true`
- Error 503 "No workers available" means all slots are in use

**GPU Concurrency:**

- Environment variables in `core/processor.py` enable concurrent GPU access:
  - `TF_FORCE_GPU_ALLOW_GROWTH=true` - Incremental VRAM allocation
  - `TF_GPU_THREAD_MODE=gpu_private` - Per-process GPU thread pools
- Check `nvidia-smi` for multiple processes using GPU simultaneously
- Low GPU usage (~3%) suggests sequential access (missing GPU config)
