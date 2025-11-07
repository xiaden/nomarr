# Nomarr

## 1. Project Overview

Nomarr provides audio auto-tagging for Lidarr using Essentia ML models. It runs as a Docker sidecar or standalone service, analyzing audio and writing tags directly into MP3/M4A metadata.

## 2. Features & Architecture

- **Unified API:** Single FastAPI app (port 8356) with public (Lidarr/webhook) and internal (CLI) endpoints.
- **Dual Authentication:** Public endpoints use `api_key`, internal endpoints use `internal_key`.
- **Warm Model Cache:** Models are lazy-loaded and shared for fast inference.
- **Multi-worker Parallelism:** Configurable worker count; each loads independent model cache (~9GB VRAM for embeddings, please plan accordingly).
- **GPU Concurrency:** TensorFlow environment variables enable concurrent GPU access.
- **Tagging:** Writes base probabilities for all labels, mood aggregation, and native multi-value tags.
- **Blocking API:** `/tag` endpoint blocks for completion by default (configurable).
- **Queue Management:** Unified tools for job listing, status, cleanup, and admin reset.
- **Native Tag Writing:** MP3 (ID3v2 TXXX), M4A (iTunes freeform atoms).

## 3. Quick Start (Docker + Lidarr)

1. Prepare host folders:

   ```bash
   mkdir -p config/db models
   ```

2. Example docker-compose snippet:

   ```yaml
   services:
     nomarr:
       build: .
       image: nomarr:latest
       container_name: nomarr
       user: "1000:1000"
       networks:
         - lidarr_network
       volumes:
         - ./models:/app/models
         - ./config:/app/config
         - /your/music/location/as/per/lidar/volume/mapping:/same/as/lidarr
       environment:
         - NOMARR_DB=/app/config/db/essentia.sqlite
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: 1
                 capabilities: [gpu]
       restart: unless-stopped
   ```

3. Start and get API key:

   ```bash
   docker compose up -d
   docker compose exec nomarr python3 -m nomarr.manage_key --show
   ```

4. Test a tag request:

   ```bash
   curl -X POST \
     -H "Authorization: Bearer <API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"path":"/music/Album/Track.mp3"}' \
     http://nomarr:8356/api/v1/tag
   ```

   Tip: In Lidarr, use a custom script or webhook to POST to `/api/v1/tag` after import.

## 4. Configuration

Configuration is loaded from multiple sources with priority (lowest to highest):

1. **Built-in defaults** (hardcoded in code)
2. **System config:** `/etc/nomarr/config.yaml`
3. **User config:** `/app/config/config.yaml` (Docker volume-mounted)
4. **Environment variables:** `TAGGER_*` or `NOMARR_TAGGER_*`
5. **Database meta table:** User customizations from web UI (operational config only)

### Infrastructure vs Operational Config

**Infrastructure config** (immutable, YAML/env only):
- `db_path` - Database file location
- `host`, `port` - API server binding
- `models_dir` - Model files directory

**Operational config** (mutable, editable via web UI):
- `namespace`, `version_tag` - Tag writing settings
- `worker_count`, `poll_interval` - Worker behavior
- `min_duration_s`, `allow_short` - Processing rules
- Cache settings, library scanner settings

### Recovery Mode

If database config gets corrupted, bypass it with an environment variable:

```yaml
environment:
  - NOMARR_IGNORE_DB_CONFIG=true
```

This forces the system to use only YAML/env config, ignoring any database-stored settings.

### Example config.yaml

Place at `config/config.yaml` (mounted at `/app/config/config.yaml`):

```yaml
models_dir: /app/models
db_path: /app/config/db/essentia.sqlite
namespace: essentia
version_tag: essentia_at_version
min_duration_s: 7
allow_short: false
overwrite_tags: true
host: 0.0.0.0
port: 8356
blocking_mode: true
blocking_timeout: 3600
poll_interval: 2
worker_enabled: true
worker_count: 1
cleanup_age_hours: 168
```

## 5. CLI Usage

Invoke the CLI via the `nom` wrapper script inside the container:

```bash
nom run /music/Album --recursive
nom watch
nom queue /music/Album
nom list --limit 50
nom remove --all
nom admin-reset --stuck
nom cleanup --hours 168
nom show-tags /music/Track.mp3
nom info
nom cache-refresh
```

All commands use the internal API for warm cache and real-time progress when available.

## 6. Web UI

Nomarr includes a browser-based web UI for monitoring and controlling the tagging system.

### Accessing the Web UI

1. Navigate to `http://<server-ip>:8356/` (or `http://nomarr:8356/` from same Docker network)
2. Log in with the admin password (auto-generated on first run)

### Admin Password Management

The admin password is automatically generated on the first API startup. To view, verify, or reset it:

```bash
# Inside the container
docker compose exec nomarr python3 -m nomarr.manage_password --show

# Verify a password
docker compose exec nomarr python3 -m nomarr.manage_password --verify

# Reset to a new password (prompts twice for confirmation)
docker compose exec nomarr python3 -m nomarr.manage_password --reset
```

**Initial password retrieval:** Check container logs after first startup:
```bash
docker compose logs nomarr | grep "Admin password"
```

You can also set a custom password in `config/config.yaml`:
```yaml
admin_password: your_secure_password_here
```

### Web UI Features

- **Process Tab:** Process single files or batches, with real-time streaming progress
- **Queue Tab:** View and manage queued jobs (pause, resume, remove)
- **List Jobs Tab:** Paginated job list with filtering by status
- **Admin Tab:** Worker control (pause/resume), cache refresh, queue cleanup, reset stuck jobs
- **Info Tab:** System information, cache status, worker stats, model counts

### Authentication Architecture

The web UI uses a three-layer authentication system:
1. **Browser → Web API:** Session-based authentication with admin password
2. **Web API → Internal API:** Server-side proxy using `internal_key` (never exposed to browser)
3. **External → Public API:** Direct API access using `api_key` (for Lidarr/webhooks)

This ensures the sensitive `internal_key` remains server-side while providing secure browser access.

## 7. API Reference & Integration

- **Public API** (port 8356, requires `api_key`):
  - POST `/api/v1/tag` { path, force? } → queues job; blocks until done by default
  - GET `/api/v1/status/{job_id}` → job details
  - GET `/api/v1/list?limit=50&offset=0&status=pending` → list jobs with pagination
  - POST `/admin/queue/cleanup` → remove old jobs
  - POST `/admin/worker/pause` / `/admin/worker/resume`
  - POST `/admin/cache/refresh` → rebuild predictor cache
- **Internal API** (same port, requires `internal_key`):
  - POST `/internal/process_direct` { path, force? } → process immediately
  - POST `/internal/process_stream` { path, force? } → SSE streaming
  - POST `/internal/batch_process` { paths[], force? } → batch process
  - GET `/internal/health` → cache/worker status
- **Status values:** `pending`, `running`, `done`, `skipped`, `error`
- See `docs/API_REFERENCE.md` for full schemas and Lidarr webhook examples.

## 8. Tagging Details

- Tags are written under the `essentia:` namespace.
- Base probabilities for all labels; tiers for selected labels.
- Mood aggregation: `mood-strict`, `mood-regular`, `mood-loose` as native multi-value tags.
- Example:

  ```
  essentia:yamnet_relaxed = 0.8941
  essentia:yamnet_relaxed_tier = high
  essentia:mood-strict = ["relaxed", "not happy", "not party", "not aggressive"]
  ```

## 9. Troubleshooting

- No tags written: Check container user permissions on `/music` and `/app/config`.
- Slow first run: Models warm into memory; subsequent jobs reuse cache.
- Changed models: Call `POST /admin/cache/refresh`.
- Ensure Lidarr and Nomarr see the same absolute file paths.
- Low GPU usage: Ensure `TF_FORCE_GPU_ALLOW_GROWTH=true` is set in `processor.py`.
- "No workers available": All worker slots are in use. Wait or increase `worker_count`.
- Skipped jobs: Files already tagged with the current version are marked as `skipped`. Use CLI `admin-reset --stuck` to reset stuck jobs, and `remove --status skipped` to clear skipped jobs if needed.

## 10. Documentation Map

- Start here: `docs/README.md`
- API reference: `docs/API_REFERENCE.md`
- Model layout: `docs/modelsinfo.md`, `docs/MODEL_WIRING_VALIDATION.md`
- Deployment guide: `docs/DEPLOYMENT.md`

## 11. Credits

Built on [Essentia](https://essentia.upf.edu/) (© Music Technology Group, Universitat Pompeu Fabra)