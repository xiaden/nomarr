# API Reference

**Audience:** Developers integrating Nomarr with automation tools, Lidarr, or custom scripts.

Nomarr provides a REST API for file processing, library operations, system monitoring, and worker management. All endpoints return JSON responses.

**Note:** Queue-based job endpoints have been removed with the discovery-based worker system. File processing now uses direct database queries instead of a separate job queue.

---

## Base URL

```
http://localhost:8356/api
```

**Versions:**
- `/api/v1/*` - Legacy API (maintained for backward compatibility)
- `/api/web/*` - Modern web UI API (preferred for new integrations)

---

## Authentication

### Web Endpoints (`/api/web/*`)

Session-based authentication:

1. Login via `/api/web/auth/login` to get session token
2. Include token in `Authorization: Bearer <token>` header
3. Session expires after inactivity (configurable, default 24 hours)

**Example:**
```bash
# Login
curl -X POST http://localhost:8356/api/web/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your-admin-password"}'

# Response
{
  "session_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "expires_in": 86400
}

# Use session token
curl http://localhost:8356/api/web/queue/queue-depth \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

### Legacy Endpoints (`/api/v1/*`)

API key authentication (deprecated but maintained):

```bash
# Get current API key
docker exec nomarr python3 -m nomarr.manage_key --show

# Generate new API key
docker exec nomarr python3 -m nomarr.manage_key --generate

# Use API key
curl -H "Authorization: Bearer <API_KEY>" \
  http://localhost:8356/api/v1/info
```

---Processing Endpoints

### POST /api/web/processing/process-files

Enqueue files for ML tagging and processing.

**Request:**
```json
{
  "paths": ["/music/Artist/Album/Track.mp3"],
  "force": false
}
```

**Response:**
```json
{
  "enqueued": 1,
  "message": "Queued 1 file for processing"
}
```

**Note:** Files are tracked in `library_files` collection with `needs_tagging` field. Discovery workers query and claim files directly from the database.status": "success"
}
```

---

## Library Endpoints

### GET /api/web/libraries/stats

Get library statistics.

**Response:**
```json
{
  "total_files": 18432,
  "unique_artists": 1247,
  "unique_albums": 3201,
  "total_duration_seconds": 5443200.5
}
```

**Note:** Field names changed in recent update:
- ✅ `unique_artists` (not `total_artists`)
- ✅ `unique_albums` (not `total_albums`)
- ✅ `total_duration_seconds` (not `total_duration`)

---

### GET /api/web/libraries

List all configured libraries.

**Query Parameters:**
- `enabled_only` (bool, default: false) - Return only enabled libraries

**Response:**
```json
[
  {
    "id": 1,
    "name": "Main Library",
    "root_path": "/music",
    "is_enabled": true,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-12-05T10:00:00Z"
  }
]
```

---

### POST /api/web/libraries/{id}/scan

Start library scan.

**Request:**
```json
{
  "paths": ["/music/Artist/Album"],
  "recursive": true,
  "force": false,
  "clean_missing": true
}
```

**Response:**
```json
{
  "queued": 15,
  "message": "Queued 15 files for processing"
}
```

---

## Calibration Endpoints

### GET /api/web/calibration/status

Get calibration generation status.

**Response:**
```json
{
  "global_version": "abc123def456",
  "last_run": 1705067200000,
  "libraries": [
    {
      "library_id": "lib_001",
      "library_name": "Main Library",
      "total_files": 18432,
      "current_count": 18432,
      "outdated_count": 0,
      "percentage": 100.0
    }
  ]
}
```

**Note:** Uses histogram-based calibration stored in `calibration_state` collection. Computes p5/p95 percentiles via sparse histogram queries (memory-bounded, ~8MB for 50 heads).

---

### POST /api/web/calibration/generate-histogram

Generate histogram-based calibrations from library data.

Uses DB histogram queries to compute p5/p95 percentiles for each ML model head.

**Request:**
```json
{}
```

**Response:**
```json
{
  "version": 5,
  "library_size": 18432,
  "heads": {
    "effnet:mood_happy": {
      "model_name": "effnet",
      "head_name": "mood_happy",
      "p5": 0.15,
      "p95": 0.87,
      "n": 18432
    }
  },
  "saved_files": {
    "effnet:mood_happy": "/app/models/effnet/heads/mood_happy-calibration-v5.json"
  },
  "summary": {
    "total_heads": 17,
    "completed_heads": 17
  }
}
```

**Note:** Requires `calibrate_heads: true` in config.

---

## Worker Endpoints

### POST /api/web/worker/pause

Pause all workers (stop picking up new jobs).

**Response:**
```json
{
  "status": "success",
  "message": "All workers paused"
}
```

**Behavior:**
- Workers finish current job
- Workers remain alive but idle
- No new jobs picked up until resumed

---

### POST /api/web/worker/resume

Resume all workers.

**Response:**
```json
{
  "status": "success",
  "message": "All workers resumed"
}
```

---

### POST /api/web/worker/restart

Restart API server (useful after config changes).

**Response:**
```json
{
  "status": "success",
  "message": "API server is restarting... Please refresh the page in a few seconds."
}
```

**Note:** Connection will be lost during restart (~5-10 seconds).

---

## Analytics Endpoints

### GET /api/web/analytics/tag-frequencies

Get tag frequency statistics.

**Query Parameters:**
- `limit` (int, default: 50) - Number of tags to return

**Response:**
```json
{
  "tag_frequencies": [
    {
      "tag_key": "nom:mood_happy",
      "total_count": 3421,
      "unique_values": 3421
    }
  ]
}
```

---

### GET /api/web/analytics/mood-distribution

Get mood distribution across library.

**Response:**
```json
{
  "mood_distribution": [
    {
      "mood": "happy",
      "count": 3421,
      "percentage": 18.5
    }
  ]
}
```

---

### GET /api/web/analytics/tag-correlations

Get tag correlation matrix.

**Query Parameters:**
- `top_n` (int, default: 20) - Number of top correlations

**Response:**
```json
{
  "mood_correlations": {
    "happy": {
      "party": 0.85,
      "energetic": 0.72
    }
  },
  "mood_tier_correlations": {
    "happy": {
      "tier_s": 0.45,
      "tier_a": 0.35
    }
  }
}
```

---

## Navidrome Endpoints

### GET /api/web/navidrome/preview

Preview tags available for Navidrome config.

**Response:**
```json
{
  "namespace": "nom",
  "tag_count": 42,
  "tags": [
    {
      "tag_key": "nom:mood_happy",
      "type": "text",
      "is_multivalue": false,
      "summary": "Mood: Happy",
      "total_count": 3421
    }
  ]
}
```

---

### GET /api/web/navidrome/config

Generate Navidrome TOML configuration.

**Response:**
```json
{
  "namespace": "nom",
  "config": "[Tags]\nGenres = ['genre']\nMoods = ['nom:mood_happy', 'nom:mood_sad']"
}
```

---

### POST /api/web/navidrome/playlists/preview

Preview Smart Playlist query results.

**Request:**
```json
{
  "query": "nom:mood_happy is true",
  "preview_limit": 10
}
```

**Response:**
```json
{
  "matched_tracks": 3421,
  "preview": [
    {
      "path": "/music/Artist/Album/Track.mp3",
      "title": "Happy Song",
      "artist": "Artist Name"
    }
  ]
}
```

---

### POST /api/web/navidrome/playlists/generate

Generate Navidrome Smart Playlist (.nsp file).

**Request:**
```json
{
  "query": "nom:mood_happy is true",
  "playlist_name": "Happy Mood",
  "comment": "Tracks with happy mood",
  "limit": 500,
  "sort": "random"
}
```

**Response:**
```json
{
  "playlist_name": "Happy Mood",
  "query": "nom:mood_happy is true",
  "content": "{\n  \"name\": \"Happy Mood\",\n  \"comment\": \"Tracks with happy mood\",\n  ..."
}
```

---

## Config Endpoints

### GET /api/web/config

Get current configuration (user-editable subset).

**Response:**
```json
{
  "models_dir": "/app/models",
  "library_auto_tag": true,
  "file_write_mode": "native",
  "namespace": "nom"
}
```

---

### POST /api/web/config

Update configuration value.

**Request:**
```json
{
  "key": "library_auto_tag",
  "value": "false"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Configuration updated successfully"
}
```

**Note:** Some settings require server restart to take effect.

---

## SSE (Server-Sent Events)

### GET /api/web/events/status

Real-time state updates via Server-Sent Events.

**Event Types:**

**1. Queue Status Updates:**
```
event: queue:status
data: {"pending": 10, "running": 1, "completed": 245, "avg_time": 12.5, "eta": 125.0}
```

**2. Job State Changes:**
```
event: queue:jobs
data: {"id": 123, "path": "/music/Track.mp3", "status": "done", "error": null}
```

**3. Worker Status Updates:**
```
event: worker:tag:0:status
data: {"component": "worker:tag:0", "status": "healthy", "pid": 1234, "current_job": 123}
```

**4. System Health:**
```
event: system:health
data: {"status": "healthy", "errors": []}
```

**JavaScript Example:**
```javascript
const eventSource = new EventSource('/api/web/events/status', {
  headers: { 'Authorization': `Bearer ${token}` }
});

eventSource.addEventListener('queue:status', (e) => {
  const state = JSON.parse(e.data);
  console.log('Queue stats:', state);
});

eventSource.addEventListener('worker:tag:0:status', (e) => {
  const worker = JSON.parse(e.data);
  console.log('Worker status:', worker);
});
```

---

## Lidarr Integration

### Webhook Setup

Configure Lidarr to auto-tag on import:

1. **Lidarr Settings → Connect → Add Custom Script**
2. **On Import, On Upgrade**
3. **Script Path:** `/config/scripts/nomarr-autotag.sh`

**Script Example:**
```bash
#!/bin/bash
# nomarr-autotag.sh

API_KEY="your-api-key-here"
NOMARR_URL="http://nomarr:8356"

# Lidarr provides these environment variables
FILE_PATH="$lidarr_trackfile_path"

# Enqueue file for tagging
curl -X POST "$NOMARR_URL/api/v1/tag" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$FILE_PATH\",\"force\":true}" \
  --silent --show-error

echo "Queued for tagging: $FILE_PATH"
```

**Docker Compose:**
```yaml
services:
  lidarr:
    volumes:
      - ./scripts/nomarr-autotag.sh:/config/scripts/nomarr-autotag.sh:ro
      - /music:/music  # Same path as Nomarr

  nomarr:
    volumes:
      - /music:/music  # Must match Lidarr's path
```

---

## Error Responses

All endpoints return consistent error format:

**Format:**
```json
{
  "detail": "Error message describing what went wrong"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad request (invalid parameters)
- `401` - Unauthorized (missing/invalid auth)
- `403` - Forbidden (insufficient permissions)
- `404` - Not found (resource doesn't exist)
- `500` - Internal server error

**Example:**
```json
{
  "detail": "File not found: /music/invalid/path.mp3"
}
```

---

## Rate Limiting

No rate limiting currently enforced. Consider implementing client-side throttling for bulk operations:

- Library scans: Avoid multiple concurrent scans
- Queue operations: Batch job submissions when possible
- Analytics: Cache results client-side

---

## Legacy API (Deprecated)

### POST /api/v1/processing/process-files

Enqueue file for tagging (legacy v1 endpoint).

**Request:**
```json
{
  "path": "/music/Artist/Album/Track.mp3",
  "force": false
}
```

**Response:**
```json
{
  "enqueued": 1,
  "message": "Queued 1 file for processing"
}
```

**Note:** Maintained for backward compatibility. Prefer `/api/web/processing/process-files` for new integrations.

---

## Related Documentation

- [Getting Started](getting_started.md) - Installation and setup
- [Deployment Guide](deployment.md) - Production configuration
- [Navidrome Integration](navidrome.md) - Smart playlists and config
- [StateBroker & SSE](../dev/statebroker.md) - Real-time event system
- [Queue System](../dev/queues.md) - Queue internals and DTOs
