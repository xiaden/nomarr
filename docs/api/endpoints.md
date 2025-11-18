# API Endpoints Reference

Complete reference for all HTTP endpoints and CLI commands.

See also:

- [API Overview](index.md) - Authentication model and integration patterns
- [Lidarr Integration](../integration/lidarr.md) - Webhook setup guide
- [Deployment Guide](../deployment.md) - Docker configuration

---

## Table of Contents

- [Public API](#public-api) (`/api/v1/*`)
- [Admin API](#admin-api) (`/admin/*`)
- [Web UI Endpoints](#web-ui-endpoints) (`/web/*`)
- [CLI Commands](#cli-commands)

---

## Public API

All `/api/v1/*` endpoints require API key authentication except `/api/v1/info`.

**Authentication:**

```bash
Authorization: Bearer <API_KEY>
```

Get API key:

```bash
docker exec nomarr python3 -m nomarr.manage_key --show
```

### POST /api/v1/tag

Enqueue a file for tagging. Returns immediately (non-blocking) or waits for completion (blocking mode).

**Request:**

```json
{
  "path": "/music/Artist/Album/Track.mp3",
  "force": false
}
```

**Parameters:**

- `path` (string, required) - Absolute path to audio file
- `force` (boolean, optional) - Overwrite existing tags (default: false)

**Response (non-blocking mode):**

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

**Configuration:**

- Set `blocking_mode: true` in config for synchronous responses
- Set `blocking_timeout` to control maximum wait time (default: 3600s)

**Lidarr Example:**

```bash
#!/bin/bash
API_KEY="your-api-key-here"
FILE_PATH="$lidarr_trackfile_path"

curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$FILE_PATH\",\"force\":true}" \
  http://nomarr:8356/api/v1/tag
```

---

### GET /api/v1/list

List jobs with pagination and optional status filtering.

**Query Parameters:**

- `limit` (int, default: 50) - Maximum jobs to return
- `offset` (int, default: 0) - Skip first N jobs (pagination)
- `status` (string, optional) - Filter: `pending`, `running`, `done`, `error`

**Examples:**

```bash
# Get first 50 jobs
GET /api/v1/list

# Get next 50 jobs (page 2)
GET /api/v1/list?limit=50&offset=50

# Get only error jobs
GET /api/v1/list?status=error

# Get 100 done jobs, starting from offset 200
GET /api/v1/list?limit=100&offset=200&status=done
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

- `total` reflects count matching status filter (or all jobs if no filter)
- `counts` always shows totals for all statuses
- Timestamps are milliseconds since Unix epoch
- Jobs ordered by ID descending (newest first)

---

### GET /api/v1/queue

List recent jobs with summary (legacy endpoint for backward compatibility).

**Query Parameters:**

- `limit` (int, default: 25) - Maximum jobs to return (max 25)

**Response:**

```json
{
  "summary": {
    "pending": 0,
    "running": 0,
    "done": 10,
    "error": 1
  },
  "jobs": [
    {
      "job_id": 123,
      "status": "done",
      "path": "/music/Track.mp3",
      "created_at": "2025-10-26T12:00:00",
      "started_at": "2025-10-26T12:00:01",
      "finished_at": "2025-10-26T12:00:15",
      "error": null
    }
  ],
  "limit": 25
}
```

**Note:** Use `/api/v1/list` for pagination and filtering support.

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

**Status Values:**

- `pending` - Queued, waiting for worker
- `running` - Currently processing
- `done` - Completed successfully
- `error` - Failed with error message

---

### GET /api/v1/info

System information: configuration, models, queue status, worker state.

**Authentication:** Not required (public health check)

**Response:**

```json
{
  "config": {
    "db_path": "/app/config/db/nomarr.sqlite",
    "models_dir": "/app/models",
    "namespace": "nom",
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

### GET /api/v1/tags

Get tags from a processed file.

**Query Parameters:**

- `path` (string, required) - Absolute path to audio file

**Example:**

```bash
GET /api/v1/tags?path=/music/Track.mp3
```

**Response:**

```json
{
  "path": "/music/Track.mp3",
  "tags": {
    "nom:mood": "happy",
    "nom:genre": "electronic",
    "nom:energy": "high"
  }
}
```

**Note:** Tag namespace is configurable (default: `nom:`).

---

### POST /api/v1/scan

Scan library directory and enqueue all audio files.

**Request:**

```json
{
  "path": "/music/Library",
  "recursive": true,
  "force": false
}
```

**Parameters:**

- `path` (string, required) - Directory to scan
- `recursive` (boolean, default: true) - Scan subdirectories
- `force` (boolean, default: false) - Overwrite existing tags

**Response:**

```json
{
  "status": "ok",
  "scanned": 1234,
  "enqueued": 856
}
```

---

## Admin API

All `/admin/*` endpoints require API key authentication.

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

**Note:** Cannot remove running jobs. Use `/admin/queue/reset-stuck` for stuck jobs.

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

Or use query parameter:

```bash
POST /admin/queue/cleanup?max_age_hours=168
```

**Response:**

```json
{
  "status": "ok",
  "max_age_hours": 168,
  "jobs_removed": 42
}
```

**Default:** 168 hours (7 days) if not specified.

---

### POST /admin/cache/refresh

Rebuild in-memory predictor cache (discover heads, load missing, drop stale).

**Use Case:** After adding/removing model files.

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "predictors": 17
}
```

---

### POST /admin/worker/pause

Disable background worker (stops processing queue).

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": false
}
```

---

### POST /admin/worker/resume

Enable background worker (resumes queue processing).

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "worker_enabled": true
}
```

---

### POST /admin/calibration/run

Generate calibration from all library files with drift tracking.

**Requirements:**

- `calibrate_heads: true` in config (returns 403 otherwise)
- Library files must be tagged first

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "calibration": {
    "version": 3,
    "library_size": 3500,
    "heads": {
      "effnet/mood_happy": {
        "model_name": "effnet",
        "head_name": "mood_happy",
        "labels": {
          "happy": {
            "p5": 0.1,
            "p95": 0.9,
            "method": "minmax"
          }
        },
        "drift_metrics": {
          "apd_p5": 0.023,
          "apd_p95": 0.015,
          "srd": 0.067,
          "jsd": 0.142,
          "median_drift": 0.031,
          "iqr_drift": 0.089,
          "is_stable": false,
          "failed_metrics": ["apd_p5", "jsd"]
        },
        "is_stable": false,
        "reference_version": 2
      }
    },
    "saved_files": {
      "effnet/mood_happy": "/app/models/effnet/heads/mood_happy-calibration-v3.json"
    },
    "reference_updates": {
      "effnet/mood_happy": "updated"
    },
    "summary": {
      "total_heads": 17,
      "stable_heads": 12,
      "unstable_heads": 5
    }
  }
}
```

See [Calibration Guide](../calibration/index.md) for drift metrics interpretation.

---

### GET /admin/calibration/history

Query calibration run history.

**Requirements:** `calibrate_heads: true` in config

**Query Parameters:**

- `model` (string, optional) - Filter by model name
- `head` (string, optional) - Filter by head name
- `limit` (int, default: 50) - Maximum results

**Example:**

```bash
GET /admin/calibration/history?model=effnet&head=mood_happy&limit=10
```

**Response:**

```json
{
  "status": "ok",
  "count": 1,
  "runs": [
    {
      "id": 42,
      "model_name": "effnet",
      "head_name": "mood_happy",
      "version": 3,
      "file_count": 3500,
      "timestamp": 1704067200000,
      "p5": 0.12,
      "p95": 0.89,
      "range": 0.77,
      "reference_version": 2,
      "apd_p5": 0.023,
      "apd_p95": 0.015,
      "srd": 0.067,
      "jsd": 0.142,
      "median_drift": 0.031,
      "iqr_drift": 0.089,
      "is_stable": 0
    }
  ]
}
```

**Notes:**

- `is_stable` is 0 (false) or 1 (true) in SQLite
- `timestamp` is Unix milliseconds

---

### POST /admin/calibration/retag-all

Bulk enqueue all tagged files for re-tagging with final stable calibration.

**Requirements:** `calibrate_heads: true` in config

**Use Case:** After iterative calibration refinement, apply final stable calibration to entire library.

**Request:** Empty body

**Response:**

```json
{
  "enqueued": 8423,
  "message": "Enqueued 8423 tagged files for re-tagging"
}
```

---

## Web UI Endpoints

All `/web/*` endpoints require session token authentication (obtained via login).

**Authentication:** Session token (Bearer) with 24-hour expiry.

### POST /web/auth/login

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

**Get admin password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --show
```

---

### POST /web/auth/logout

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

---

### POST /web/api/process

Process a single file with SSE streaming progress.

**Request:**

```json
{
  "path": "/music/Track.mp3",
  "force": false
}
```

**Response:** Server-Sent Events (SSE) stream

**Event Types:**

- `progress` - Processing updates
- `complete` - Processing finished
- `error` - Processing failed

---

### POST /web/api/batch-process

Process multiple files synchronously.

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
    {
      "path": "/music/Track1.mp3",
      "tags_written": 42,
      "duration": 3.5
    },
    {
      "path": "/music/Track2.mp3",
      "tags_written": 38,
      "duration": 3.2
    }
  ]
}
```

---

### Queue Management (Web UI)

The following endpoints proxy public/admin APIs with session auth:

- `GET /web/api/list` - List jobs (proxies `/api/v1/list`)
- `GET /web/api/queue` - Queue summary (proxies `/api/v1/queue`)
- `GET /web/api/status/{job_id}` - Job status (proxies `/api/v1/status/{job_id}`)
- `POST /web/api/queue/remove` - Remove job (proxies `/admin/queue/remove`)
- `POST /web/api/queue/flush` - Flush jobs (proxies `/admin/queue/flush`)
- `POST /web/api/queue/cleanup` - Cleanup old jobs (proxies `/admin/queue/cleanup`)

**Request/Response:** Same as proxied endpoints.

---

### POST /web/api/queue/reset-stuck

Reset jobs stuck in "running" state to "pending".

**Request:** Empty body

**Response:**

```json
{
  "status": "ok",
  "reset_count": 3
}
```

---

### Admin Controls (Web UI)

- `POST /web/api/admin/worker/pause` - Pause worker (proxies `/admin/worker/pause`)
- `POST /web/api/admin/worker/resume` - Resume worker (proxies `/admin/worker/resume`)
- `POST /web/api/admin/cache/refresh` - Refresh cache (proxies `/admin/cache/refresh`)

**Request/Response:** Same as proxied endpoints.

---

### GET /web/api/info

Get system information (proxies `/api/v1/info`).

**Response:** Same as `/api/v1/info`.

---

### GET /web/api/health

Get cache and worker status.

**Response:**

```json
{
  "cache_initialized": true,
  "worker_count": 4,
  "available_workers": 2
}
```

---

## CLI Commands

The CLI accesses `Application` services directly (no HTTP overhead).

**Wrapper Script:**

```bash
alias nom='docker exec nomarr nom'
```

### nom run

Process files directly.

**Usage:**

```bash
nom run <path> [--recursive] [--force]
```

**Examples:**

```bash
# Process single file
nom run /music/Track.mp3

# Process directory recursively
nom run /music/Album --recursive

# Force reprocess (overwrite tags)
nom run /music/Album --recursive --force
```

---

### nom list

List queue jobs.

**Usage:**

```bash
nom list [--limit N] [--offset N] [--status STATUS]
```

**Examples:**

```bash
# List recent 50 jobs
nom list

# List first 100 jobs
nom list --limit 100

# List only errors
nom list --status error
```

---

### nom remove

Remove job from queue.

**Usage:**

```bash
nom remove <job_id> | --all
```

**Examples:**

```bash
# Remove specific job
nom remove 123

# Remove all pending/error jobs
nom remove --all
```

---

### nom show-tags

Display tags from processed file.

**Usage:**

```bash
nom show-tags <path>
```

**Example:**

```bash
nom show-tags /music/Track.mp3
```

---

### nom info

Display system information.

**Usage:**

```bash
nom info
```

---

### nom admin-reset

Reset stuck jobs.

**Usage:**

```bash
nom admin-reset --stuck
```

---

### nom cleanup

Remove old finished jobs.

**Usage:**

```bash
nom cleanup --hours N
```

**Example:**

```bash
# Remove jobs older than 7 days
nom cleanup --hours 168
```

---

### nom export-playlists

Export Navidrome smart playlists.

**Usage:**

```bash
nom export-playlists <output_dir>
```

**Example:**

```bash
nom export-playlists /path/to/navidrome/playlists
```

See [Navidrome Integration](../integration/navidrome.md) for details.

---

## Error Handling

All API responses follow consistent error format:

```json
{
  "error": "Human-readable error message",
  "detail": "Additional context (development mode only)"
}
```

**HTTP Status Codes:**

- `200` - Success
- `400` - Bad request (invalid parameters, file not found)
- `401` - Authentication required
- `403` - Forbidden (invalid credentials)
- `500` - Server error (processing failed)

---

## Further Reading

- [API Overview](index.md) - Authentication and integration patterns
- [Lidarr Integration](../integration/lidarr.md) - Webhook setup guide
- [Navidrome Integration](../integration/navidrome.md) - Smart playlist generation
- [Calibration Guide](../calibration/index.md) - Tag calibration and drift tracking
- [Deployment Guide](../deployment.md) - Docker configuration and security
