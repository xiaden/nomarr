# Deployment Guide

## Quick Start

```bash
# Build the image
docker compose build

# Start the container
docker compose up -d

# Check logs
docker compose logs -f nomarr

# You should see:
# - "Starting Application..."
# - "Starting Nomarr API on 0.0.0.0:8356..."
# - "Public endpoints: /api/v1/tag, /api/v1/queue, /api/v1/status/*, etc."
# - "Web endpoints: /web/* (requires session token)"
# - "Generated admin password: <password>" (first run only)
```

## Architecture

### Single Unified API

The container runs **one FastAPI app** via `start.py` on port 8356:

**Endpoints**:

- **Public API** (`/api/v1/*`) - requires `api_key` (for Lidarr/webhooks)
- **Admin API** (`/admin/*`) - requires `api_key` (for queue/worker management)
- **Web UI** (`/web/*`, `/web/api/*`) - requires session token from admin password login (for browser)

### Security Model

- **Two-layer authentication**:
  - `api_key` - for Lidarr webhooks and admin operations, user-managed via `manage_key.py`
  - `admin_password` - for web UI login (web endpoints), auto-generated or set in config
- All keys/passwords are stored in the database
- Web UI uses session tokens (24-hour expiry) after password login
- CLI accesses Application services directly (no HTTP authentication needed)

### Admin Password Setup

**On first startup**, an admin password is auto-generated and logged:

```bash
docker compose logs nomarr | grep "Admin password"
# Output: Generated admin password: abc123xyz789
```

**View current password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --show
```

**Verify a password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --verify
# Enter password when prompted
```

**Reset to new password:**

```bash
docker exec nomarr python3 -m nomarr.manage_password --reset
# Enter new password twice for confirmation
```

**Set password in config** (alternative to auto-generation):

```yaml
# config/config.yaml
admin_password: your_secure_password
```

If set in config, this password will be used instead of auto-generating one.

### Web UI Access

1. Open browser to `http://<server-ip>:8356/` (or `http://nomarr:8356/` from same Docker network)
2. Enter admin password (retrieve from logs or `manage_password.py --show`)
3. Session token stored in browser localStorage (24-hour expiry)
4. All web API calls use session token authentication

**Features:**

- Process files with real-time streaming progress
- View and manage queue (pause, resume, remove jobs)
- Admin controls (worker pause/resume, cache refresh, cleanup)
- System info and health monitoring
- Library management and scanning

### Cache Strategy

- **Lazy-loaded on first use**: Models are cached when first needed (not at startup)
- **Shared across all processing**: CLI and web UI access the same Application instance and model cache
- **No HTTP overhead for CLI**: CLI calls Application services directly (no API calls)

## CLI Usage

### Inside Container

The CLI runs inside the container and accesses Application services directly:

```bash
# Process files directly (no HTTP, uses Application services)
docker exec nomarr python3 -m nomarr.interfaces.cli.main run /music/Album/*.mp3

# Or use the nom wrapper script
docker exec nomarr nom run /music/Album --recursive

# Show API key (for Lidarr/webhook integration)
docker exec nomarr python3 -m nomarr.manage_key --show

# Manage admin password
docker exec nomarr python3 -m nomarr.manage_password --show

# Check queue
docker exec nomarr nom list

# Remove jobs
docker exec nomarr nom remove --all

# Show tags in a file
docker exec nomarr nom show-tags /music/Track.mp3
```

### From Host (via docker exec)

Create a shell alias for convenience:

```bash
# Add to ~/.bashrc or ~/.zshrc
alias nom='docker exec nomarr nom'

# Then use:
nom run /music/NewAlbum --recursive
nom list
nom show-tags /music/Track.mp3
nom admin-reset --stuck
nom cleanup --hours 168
```

## Lidarr Integration

### Post-Import Hook

In Lidarr → Settings → Connect → Custom Script:

**Bash script** (`/path/to/lidarr-nomarr.sh`):

```bash
#!/bin/bash
# Lidarr post-import hook for Nomarr

API_KEY="your-api-key-here"
API_URL="http://nomarr:8356"

if [ "$lidarr_eventtype" = "Download" ]; then
    for file in "$lidarr_addedtrackpaths"; do
        curl -X POST \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"path\":\"$file\",\"force\":true}" \
            "$API_URL/api/v1/tag"
    done
fi
```

Make executable: `chmod +x /path/to/lidarr-nomarr.sh`

## Network Configuration

### Same Docker Network (Recommended)

```yaml
# docker-compose.yml
services:
  nomarr:
    networks:
      - lidarr_network

  lidarr:
    networks:
      - lidarr_network

networks:
  lidarr_network:
    external: true
```

Lidarr reaches Nomarr via `http://nomarr:8356`

### Exposing to Host Network (If Needed)

```yaml
# docker-compose.yml
services:
  nomarr:
    ports:
      - "8356:8356" # Public and web endpoints
```

## Troubleshooting

### CLI Issues

The CLI accesses Application services directly (no HTTP). If you see errors:

```bash
# Check if Application is running
docker exec nomarr nom info

# Check container logs
docker compose logs nomarr | tail -50
```

### Public API Unreachable

```bash
# Check container is running
docker compose ps

# Check API health
docker exec nomarr curl -s http://127.0.0.1:8356/api/v1/info

# Check from host (if port exposed)
curl http://localhost:8356/api/v1/info
```

### Cache Issues

Models are lazy-loaded on first use. If processing hangs:

```bash
# Check model files exist
docker exec nomarr ls -lh /app/models

# Verify model discovery
docker exec nomarr python3 -c "
from nomarr.ml.models.discovery import discover_heads
heads = discover_heads('/app/models')
print(f'Found {len(heads)} heads')
"

# Force cache refresh via API
curl -X POST \
  -H 'Authorization: Bearer YOUR_API_KEY' \
  http://localhost:8356/admin/cache/refresh
```

## Monitoring

### Health Checks

```bash
# API info endpoint
curl http://localhost:8356/api/v1/info

# Or via CLI
docker exec nomarr nom info
```

### Queue Status

```bash
# Via CLI (recommended)
docker exec nomarr nom list

# Or via API
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8356/api/v1/list
```

## Security Checklist

✅ API key authentication for public/admin endpoints  
✅ Admin password for web UI (session-based)  
✅ Container runs as non-root user (1000:1000)  
✅ API key auto-generated and stored in DB  
✅ CLI accesses services directly (no network exposure)

## Performance

- **First processing after startup**: ~2-10s model load (lazy-loaded on demand)
- **Subsequent processing**: Instant (models cached in memory)
- **Lidarr webhook processing**: ~2-5s per file (queue-based by default)
- **Multi-worker parallelism**: Configurable worker count (default: 1, increases VRAM usage)

## Upgrading

```bash
# Pull latest changes
git pull

# Rebuild image
docker compose build

# Restart container
docker compose up -d

# Verify
docker compose logs -f nomarr
```

Model cache is lazy-loaded, so no manual refresh needed unless you change models.
