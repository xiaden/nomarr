# Nomarr Docker Development Setup

Local development environment for Nomarr with ArangoDB and the application.

## Quick Start

```bash
# From the repo root:
docker compose -f .docker/compose.yaml up -d
```

## Services

- **ArangoDB**: `http://localhost:8529` (root password: `nomarr_dev_password`)
- **Nomarr Web UI**: `http://localhost:8000`
- **Nomarr API**: `http://localhost:8000/api`

## Logs

View application logs:

```bash
docker compose -f .docker/compose.yaml logs -f nomarr
```

View ArangoDB logs:

```bash
docker compose -f .docker/compose.yaml logs -f arangodb
```

## Stop

```bash
docker compose -f .docker/compose.yaml down
```

## Stop + Wipe Data

```bash
docker compose -f .docker/compose.yaml down -v
```

## Configuration

### Environment Files

- `.env` - Default configuration (committed)
- `.env.local` - Local overrides (not committed, for your machine-specific settings)

Edit `.docker/.env` to customize defaults:

- `ARANGO_ROOT_PASSWORD` - ArangoDB admin password
- `NOMARR_API_HOST` / `NOMARR_API_PORT` - API binding
- `NOMARR_LOG_LEVEL` - Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- `LIBRARY_ROOT` - Container path to music library (default: `/media`)

For local changes, create `.docker/.env.local`:
```
NOMARR_LOG_LEVEL=DEBUG
```

### Windows Network Mounts (X: drive) - WSL2 Backend

Docker Desktop on Windows with WSL2 backend has limitations with network drive mounts. The default compose tries `X:/media` but may not work depending on your setup.

**If X: mount fails (shows empty directory in container):**

1. **Inside the container, mount via SMB** (most reliable for WSL2):
   ```bash
   docker exec -it nomarr-app bash
   apt-get update && apt-get install -y cifs-utils
   mkdir -p /media
   mount -t cifs //192.168.220.254/data/media /media -o username=guest,password=
   ```

2. **Or test if Windows path works** (requires Docker Desktop file sharing enabled):
   - Docker Desktop → Settings → Resources → File Sharing
   - Ensure `X:\` is listed
   - Edit `compose.yaml` volumes: change `X:/media` to `X:/media` (may already work)

3. **Or use a local directory instead**:
   - Edit `.env.local` or `compose.yaml` to mount a different path
   - Example: `-v /some/local/music:/media:ro`

See `.env.local.example` for configuration hints.

## Tips

- **Attach shell**: `docker exec -it nomarr-app bash`
- **ArangoDB shell**: `docker exec -it nomarr-arangodb arangosh --server.authentication false`
- **Restart service**: `docker compose -f .docker/compose.yaml restart nomarr`
- **Rebuild image**: `docker compose -f .docker/compose.yaml up -d --build`
- **View specific log lines**: `docker compose -f .docker/compose.yaml logs nomarr --tail 50`

