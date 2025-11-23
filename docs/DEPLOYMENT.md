# Deployment Guide

Complete guide for deploying Nomarr in production or development environments.

See also:

- [Getting Started](getting_started.md) - Initial installation and configuration
- [API Reference](api/endpoints.md) - Full HTTP and CLI API documentation
- [Navidrome Integration](integration/navidrome.md) - Smart playlist generation

---

## Quick Start

```bash
# Clone and start
git clone https://github.com/yourusername/nomarr.git
cd nomarr
docker compose build
docker compose up -d

# Verify running
docker compose ps
docker compose logs -f nomarr
```

The API will be available at `http://localhost:8356`.

---

## Architecture

### Unified API Design

Nomarr uses a **single FastAPI application** (`nomarr.app:app`) that serves three distinct endpoint groups:

| Endpoint Group | Auth Requirement       | Purpose                                            |
| -------------- | ---------------------- | -------------------------------------------------- |
| `/api/v1/*`    | API key (Bearer token) | Public API for Lidarr webhooks, CLI access         |
| `/admin/*`     | API key (Bearer token) | Admin operations (cache refresh, queue management) |
| `/web/*`       | Session token (login)  | Web UI endpoints (dashboard, queue, tags)          |

**Key Characteristics:**

- Single FastAPI app on port 8356
- Shared `Application` instance across all interfaces
- Shared model cache (lazy-loaded)
- CLI accesses `Application` services directly (no HTTP overhead)

### Security Model

**Two-Layer Authentication:**

1. **API Key (Bearer Token)**

   - Used for `/api/v1/*` and `/admin/*` endpoints
   - Auto-generated on first startup and stored in DB
   - Retrieve with: `docker exec nomarr python3 -m nomarr.manage_key --show`
   - Used by Lidarr webhooks and programmatic access

2. **Admin Password (Session-Based)**
   - Used for `/web/*` UI endpoints
   - Auto-generated on first startup or set via `admin_password` in config
   - Retrieve with: `docker exec nomarr python3 -m nomarr.manage_password --show`
   - Web UI login at `http://localhost:8356/web/login`

### Cache Strategy

- **Lazy-loaded**: Models load on first use, not at startup
- **Shared**: CLI and web UI access the same `Application` instance and model cache
- **Persistent**: Cache remains in memory across requests
- **No HTTP overhead for CLI**: CLI calls `Application` services directly

---

## CLI Usage

### Inside Container

The CLI runs inside the container and accesses `Application` services directly:

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

````bash
# Add to ~/.bashrc or ~/.zshrc
alias nom='docker exec nomarr nom'

# Then use:
nom run /music/NewAlbum --recursive
nom list
nom show-tags /music/Track.mp3
nom admin-reset --stuck

---

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
````

Make executable: `chmod +x /path/to/lidarr-nomarr.sh`

For detailed setup and troubleshooting, see [Lidarr Integration Guide](integration/lidarr.md).

---

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

---

## Troubleshooting

### CLI Issues

The CLI accesses `Application` services directly (no HTTP). If you see errors:

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
from nomarr.components.ml.models.discovery import discover_heads
heads = discover_heads('/app/models')
print(f'Found {len(heads)} heads')
"

# Force cache refresh via API
curl -X POST \
  -H 'Authorization: Bearer YOUR_API_KEY' \
  http://localhost:8356/admin/cache/refresh
```

---

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

---

## Security Checklist

✅ API key authentication for public/admin endpoints  
✅ Admin password for web UI (session-based)  
✅ Container runs as non-root user (1000:1000)  
✅ API key auto-generated and stored in DB  
✅ CLI accesses services directly (no network exposure)

---

## Performance

- **First processing after startup**: ~2-10s model load (lazy-loaded on demand)
- **Subsequent processing**: Instant (models cached in memory)
- **Lidarr webhook processing**: ~2-5s per file (queue-based by default)
- **Multi-worker parallelism**: Configurable worker count (default: 1, increases VRAM usage)

---

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
