# Deployment Guide

## Quick Start

```bash
# Build the image
docker compose build

# Start the container
docker compose up -d

# Check logs
docker compose logs -f autotag

# You should see:
# - "Warming up model predictor cache..."
# - "Starting Essentia Autotag API on 0.0.0.0:8356..."
# - "Public endpoints: /tag, /queue, /status/*, etc."
# - "Internal endpoints: /internal/* (requires internal_key)"
# - "Web endpoints: /web/* (requires session token)"
# - "Generated admin password: <password>" (first run only)
```

## Architecture

### Single Unified API

The container runs **one FastAPI app** via `start_api.py` on port 8356:

**Endpoints**:
- **Public** (`/tag`, `/queue`, `/status`, `/admin/*`) - requires `api_key` (for Lidarr)
- **Internal** (`/internal/*`) - requires `internal_key` (for CLI)
- **Web** (`/web/*`, `/web/api/*`) - requires session token from admin password login (for browser UI)

### Security Model

- **Three-layer authentication**:
  - `api_key` - for Lidarr webhooks (public endpoints), user-managed via `manage_key.py`
  - `internal_key` - for CLI access (internal endpoints), auto-generated and hidden
  - `admin_password` - for web UI login (web endpoints), auto-generated or set in config
  
- All keys/passwords are stored in the database
- Web UI uses session tokens (24-hour expiry) after password login
- Web endpoints proxy to internal API server-side (never expose `internal_key` to browser)

### Admin Password Setup

**On first startup**, an admin password is auto-generated and logged:
```bash
docker compose logs autotag | grep "Admin password"
# Output: Generated admin password: abc123xyz789
```

**View current password:**
```bash
docker exec autotag python3 -m nomarr.manage_password --show
```

**Verify a password:**
```bash
docker exec autotag python3 -m nomarr.manage_password --verify
# Enter password when prompted
```

**Reset to new password:**
```bash
docker exec autotag python3 -m nomarr.manage_password --reset
# Enter new password twice for confirmation
```

**Set password in config** (alternative to auto-generation):
```yaml
# config/config.yaml
admin_password: your_secure_password
```

If set in config, this password will be used instead of auto-generating one.

### Web UI Access

1. Open browser to `http://<server-ip>:8356/` (or `http://autotag:8356/` from same Docker network)
2. Enter admin password (retrieve from logs or `manage_password.py --show`)
3. Session token stored in browser localStorage (24-hour expiry)
4. All web API calls use session token authentication

**Features:**
- Process files with real-time streaming progress
- View and manage queue (pause, resume, remove jobs)
- Admin controls (worker pause/resume, cache refresh, cleanup)
- System info and health monitoring

### Cache Strategy

- **Warm on startup**: Predictor cache loads once when container starts
- **Shared across all processing**: Worker, CLI, web UI, and direct endpoints all use the same in-memory cache
- **No warmup delays**: CLI and web UI call internal API → instant processing with warm cache

## CLI Usage

### Inside Container

```bash
# Process files (uses internal API automatically)
docker exec -it essentia_autotag python3 -m essentia_autotag.cli run /music/Album/*.mp3

# Show API keys (public key only, internal key is hidden)
docker exec -it essentia_autotag python3 -m essentia_autotag.manage_key --show

# Manage admin password
docker exec -it essentia_autotag python3 -m essentia_autotag.manage_password --show

# Check queue
docker exec -it essentia_autotag python3 -m essentia_autotag.cli list
```

### From Host (via docker exec)

Create a shell alias for convenience:

```bash
# Add to ~/.bashrc or ~/.zshrc
alias autotag='docker exec -it essentia_autotag python3 -m essentia_autotag.cli'

# Then use:
autotag run /music/NewAlbum --recursive
autotag list
autotag show-tags /music/Track.mp3
```

## Lidarr Integration

### Post-Import Hook

In Lidarr → Settings → Connect → Custom Script:

**Bash script** (`/path/to/lidarr-autotag.sh`):
```bash
#!/bin/bash
# Lidarr post-import hook for Essentia Autotag

API_KEY="your-api-key-here"
API_URL="http://autotag:8356"

if [ "$lidarr_eventtype" = "Download" ]; then
    for file in "$lidarr_addedtrackpaths"; do
        curl -X POST \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"path\":\"$file\"}" \
            "$API_URL/tag"
    done
fi
```

Make executable: `chmod +x /path/to/lidarr-autotag.sh`

## Network Configuration

### Same Docker Network (Recommended)

```yaml
# docker-compose.yml
services:
  autotag:
    networks:
      - lidarr_network
  
  lidarr:
    networks:
      - lidarr_network

networks:
  lidarr_network:
    external: true
```

Lidarr reaches autotag via `http://autotag:8356`

### Exposing to Host Network (If Needed)

```yaml
# docker-compose.yml
services:
  autotag:
    ports:
      - "8356:8356"  # Single unified API port
```

**Note**: Internal endpoints are protected by separate `internal_key` authentication (same port, different auth).

## Troubleshooting

### CLI shows "Internal API not available"

```bash
# Check if API is running
docker exec -it essentia_autotag curl -s http://127.0.0.1:8356/internal/health

# Check logs for startup
docker compose logs autotag | grep "Starting Essentia"
```

If healthy, CLI will fall back to local processing (slower, needs to load cache).

### Public API unreachable

```bash
# Check container is running
docker compose ps

# Check public API health
docker exec -it essentia_autotag curl -s http://127.0.0.1:8356/info

# Check from host (if port exposed)
curl http://localhost:8356/info
```

### Cache warmup taking too long

Normal on first boot (10-30 seconds). If it hangs:

```bash
# Check model files
docker exec -it essentia_autotag ls -lh /app/models

# Ensure both .json and .pb exist for each head
docker exec -it essentia_autotag python3 -c "
from essentia_autotag.discovery import discover_heads
heads = discover_heads('/app/models')
print(f'Found {len(heads)} heads')
"
```

## Monitoring

### Health Checks

```bash
# Public API
curl http://localhost:8356/info

# Internal API (requires internal_key)
docker exec -it essentia_autotag curl http://127.0.0.1:8356/internal/health
```

### Queue Status

```bash
docker exec -it essentia_autotag python3 -m essentia_autotag.cli list

# Or via API
curl -H "Authorization: Bearer YOUR_KEY" http://localhost:8356/queue
```

## Security Checklist

✅ Separate `internal_key` (different from `api_key`)  
✅ Internal endpoints require authentication even on localhost  
✅ Container runs as non-root user (1000:1000)  
✅ Both keys auto-generated and stored in DB  
✅ Keys viewable only inside container via `manage_key.py`

## Performance

- **First run after container start**: ~10-30s warmup (loads all models)
- **Subsequent CLI runs**: Instant (reuses API cache via internal endpoints)
- **Lidarr webhook processing**: ~2-5s per file (queue-based, non-blocking)
- **Parallel processing**: Not implemented (sequential by design for stability)

## Upgrading

```bash
# Pull latest changes
git pull

# Rebuild image
docker compose build

# Restart container (cache rebuilds on startup)
docker compose up -d

# Verify
docker compose logs -f autotag
```

Cache is rebuilt automatically on container start, so no manual refresh needed after upgrade.
