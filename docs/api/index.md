# API Overview

Nomarr provides three interfaces for interacting with the system:

1. **HTTP API** - RESTful endpoints for programmatic access
2. **CLI** - Command-line interface for direct file processing
3. **Web UI** - Browser-based interface for management and monitoring

---

## Authentication Model

Nomarr uses a **two-layer authentication system**:

### 1. API Key (Bearer Token)

Used for **programmatic access** to HTTP endpoints:

- `/api/v1/*` - Public API (webhooks, batch operations)
- `/admin/*` - Admin API (cache, queue, worker management)

**Retrieve API Key:**

```bash
docker exec nomarr python3 -m nomarr.manage_key --show
```

**Usage:**

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8356/api/v1/info
```

### 2. Admin Password (Session-Based)

Used for **web UI access** to browser endpoints:

- `/web/*` - Web UI pages and API endpoints

**Retrieve Admin Password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --show
```

**Usage:**

1. Navigate to `http://localhost:8356/web/login`
2. Enter admin password
3. Session token stored in browser (24-hour expiry)

---

## HTTP API Structure

| Endpoint Group | Authentication | Purpose                                                 |
| -------------- | -------------- | ------------------------------------------------------- |
| `/api/v1/*`    | API Key        | Lidarr webhooks, programmatic tagging, queue inspection |
| `/admin/*`     | API Key        | Cache refresh, worker control, cleanup operations       |
| `/web/*`       | Session Token  | Browser-based UI and management                         |

### Key Endpoints

**Public API (`/api/v1/*`)**

- `POST /api/v1/tag` - Queue file for tagging
- `GET /api/v1/list` - List queue jobs (paginated)
- `GET /api/v1/status/{job_id}` - Get job status
- `GET /api/v1/info` - System info (no auth required)
- `GET /api/v1/tags` - Get tags from processed file
- `POST /api/v1/scan` - Scan library directory

**Admin API (`/admin/*`)**

- `POST /admin/cache/refresh` - Reload model cache
- `POST /admin/worker/pause` - Pause background worker
- `POST /admin/worker/resume` - Resume background worker
- `POST /admin/cleanup` - Remove old jobs
- `GET /admin/queue/summary` - Queue statistics

**Web UI (`/web/*`)**

- `GET /web/login` - Login page
- `POST /web/api/login` - Authenticate with admin password
- `GET /web/dashboard` - Main dashboard
- `GET /web/queue` - Queue management UI
- `GET /web/process` - File processing UI
- See [Web UI Endpoints](endpoints.md#web-ui-endpoints) for full list

---

## CLI Architecture

The CLI accesses `Application` services **directly** without HTTP overhead:

- No authentication required (direct in-process calls)
- Shared model cache with HTTP API and web UI
- Same queue and database as HTTP interfaces
- Ideal for batch processing and scripting

**Common Commands:**

```bash
# Process files
nom run /music/Album --recursive

# Queue management
nom list
nom remove --all

# Tag inspection
nom show-tags /music/Track.mp3

# Admin operations
nom admin-reset --stuck
nom cleanup --hours 168
```

See [CLI Reference](endpoints.md#cli-commands) for complete command documentation.

---

## Integration Patterns

### Lidarr Webhook

Nomarr is designed for seamless Lidarr integration:

```bash
# Lidarr custom script (on import complete)
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$lidarr_trackfile_path\",\"force\":true}" \
  http://nomarr:8356/api/v1/tag
```

See [Lidarr Integration Guide](../integration/lidarr.md) for detailed setup.

### Navidrome Smart Playlists

Generate Navidrome smart playlists based on tag analysis:

```bash
# Export playlists to Navidrome config directory
nom export-playlists /path/to/navidrome/playlists
```

See [Navidrome Integration Guide](../integration/navidrome.md) for configuration.

---

## Configuration

Tags are written to configurable namespace fields (default: `nom:`):

```yaml
# config/config.yaml
tag_namespace: nom # Creates nom:mood, nom:genre, etc.
```

This allows Nomarr tags to coexist with existing metadata without conflicts.

**Note:** The tag namespace is **configurable**, not hardcoded. All documentation examples use `nom:` as the default, but you can set any namespace you prefer.

---

## Error Handling

All API responses follow a consistent error format:

```json
{
  "error": "Human-readable error message",
  "detail": "Additional context (development mode only)"
}
```

HTTP status codes:

- `200` - Success
- `400` - Invalid request (bad parameters, file not found)
- `401` - Authentication required
- `403` - Forbidden (wrong credentials)
- `500` - Server error (processing failed)

---

## Rate Limiting

**None currently implemented.**

For production deployments with public exposure, consider:

- Reverse proxy rate limiting (nginx, Caddy)
- API gateway (Kong, Tyk)
- Queue-based processing (built-in via `/api/v1/tag` non-blocking mode)

---

## Further Reading

- [API Endpoints Reference](endpoints.md) - Complete endpoint documentation
- [Lidarr Integration](../integration/lidarr.md) - Webhook setup and troubleshooting
- [Navidrome Integration](../integration/navidrome.md) - Smart playlist generation
- [Deployment Guide](../deployment.md) - Docker setup and security
- [Getting Started](../getting_started.md) - Installation and first-time setup
