---
name: docker
description: Reference for the Nomarr Docker development environment. Use when working with Docker containers, running e2e tests, querying ArangoDB directly, debugging prod-like issues, testing DB migrations, or interacting with the containerized Nomarr API. Contains credentials, ports, PowerShell snippets, AQL queries, and collection schema.
---

# Docker Development Environment

The containerized dev environment lives in `.devcontainer/`. The compose file is `.devcontainer/docker-compose.dev.yaml` and brings up two services:

| Service name | Container name | Image |
| --- | --- | --- |
| `nomarr` | `nomarr-dev` | built from repo `dockerfile` |
| `nomarr-arangodb` | `nomarr-arangodb-dev` | `arangodb:3.12` |

The `devcontainer.json` wires this compose stack into VS Code Dev Containers. The workspace folder inside the container is `/workspace` (the full repo, read-only). The active Python source is at `/app/nomarr` (bind-mounted from `../nomarr` — editable without rebuild).

Key paths inside `.devcontainer/` (all gitignored except the compose and JSON files):

| Path | Purpose |
| --- | --- |
| `docker-compose.dev.yaml` | Compose definition |
| `devcontainer.json` | VS Code Dev Containers config |
| `nomarr.dev.env` | Env vars for the `nomarr` service |
| `nomarr-arangodb.dev.env` | Env vars for the `nomarr-arangodb` service |
| `config/` | Nomarr runtime config — populated on first start |
| `arangodb-data/` | ArangoDB data directory — delete to reset the DB |
| `test-media/` | Drop audio files here to create a scannable library |

Templates for the env files live in `docker/nomarr.env.example` and `docker/nomarr-arangodb.env.example`.

---

## CRITICAL: Windows Docker Context

On Windows with Docker Desktop, the default Docker context sometimes does not point to the WSL2/Hyper-V backend where containers actually run. Commands will appear to succeed but produce no output, or report that no containers exist.

**Check first:**
```powershell
docker context ls
```

If `desktop-linux` exists and is not marked with `*`, set it permanently:
```powershell
docker context use desktop-linux
```

Or prefix every command with `--context desktop-linux`:
```powershell
docker --context desktop-linux ps
```

If `docker context ls` itself fails or returns empty, Docker Desktop is not running.

---

## CRITICAL: GPU Requirement

**`nomarr-dev` requires an NVIDIA GPU.** The compose file declares:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

If NVIDIA Container Toolkit is not installed or no GPU is present, `docker compose up` fails immediately with a message like `could not select device driver "nvidia"`. This is the most common reason `compose up` fails on first run. There is no CPU-only fallback for the devcontainer.

---

## When to Use Docker vs Native Dev

**Use Docker when:**

- Reproducing prod-reported issues not visible in native dev
- Running e2e tests with Playwright (`npx playwright test` from the host against the running container)
- Testing DB migration behavior on a real ArangoDB instance
- Verifying ML inference or audio analysis in a prod-like environment

**Use native dev when:**

- Writing/debugging backend services (faster iteration, no restart cycle)
- Running lint/type checks
- Unit/integration tests
- Iterating on frontend components

---

## Credentials & Ports

- **Nomarr admin password**: `.devcontainer/config/config.yaml` → `admin_password` (set on first run)
- **ArangoDB password**: `.devcontainer/nomarr-arangodb.dev.env` → `ARANGO_ROOT_PASSWORD`
- **Nomarr API**: `http://127.0.0.1:8356`
- **ArangoDB Web UI**: `http://127.0.0.1:8529`

**CRITICAL: Use `127.0.0.1` not `localhost`** — On Windows, `localhost` resolves to IPv6 (`::1`) first. Docker only binds IPv4, so `localhost` hangs ~21 seconds before falling back. Every API call in this skill uses `127.0.0.1`.

Both ports are published directly by the compose file (`ports:` binding) **and** forwarded by VS Code via `devcontainer.json` `forwardPorts`. They are reachable from the host regardless of whether VS Code is connected.

---

## Env File Bootstrap

The `.devcontainer/` env files are gitignored and must be created before `compose up` will work. Copy from templates and customize:

```powershell
# From the repo root
Copy-Item docker/nomarr.env.example .devcontainer/nomarr.dev.env
Copy-Item docker/nomarr-arangodb.env.example .devcontainer/nomarr-arangodb.dev.env
```

Then edit `.devcontainer/nomarr.dev.env`:
```
ARANGO_HOST=http://nomarr-arangodb:8529     # service name on the compose network — do NOT use localhost
ARANGO_ROOT_PASSWORD=nomarr_dev_password    # must match nomarr-arangodb.dev.env
```

Edit `.devcontainer/nomarr-arangodb.dev.env`:
```
ARANGO_ROOT_PASSWORD=nomarr_dev_password
ARANGO_NO_AUTH=0
```

`ARANGO_HOST` uses the compose service name (`nomarr-arangodb`), not `localhost`. Containers reach each other via the internal compose network.

---

## devcontainer Lifecycle

Understanding the difference between Rebuild, Restart, and Reopen prevents wasted minutes and data loss.

### Rebuild Container (Dev Containers: Rebuild Container)

Tears down the compose stack, rebuilds the `nomarr-dev` Docker image from `dockerfile`, and restarts everything.

**When you need it:**
- `dockerfile` changed
- `requirements.txt` changed
- `dockerfile.base` changed
- Extensions or settings in `devcontainer.json` changed

**Cost:** Full image build (minutes). ArangoDB data is preserved (bind mount in `.devcontainer/arangodb-data/`). Nomarr config is preserved (bind mount in `.devcontainer/config/`).

### Restart Container (Dev Containers: Restart Container)

Kills and restarts the `nomarr-dev` container without rebuilding the image. The Python source bind mount (`../nomarr:/app/nomarr`) means code edits are already visible to the container filesystem — but the running process must restart to reload them.

**When you need it:** Any Python code change you want to pick up without a full rebuild.

**From the terminal (faster than the palette):**
```powershell
docker compose -f .devcontainer/docker-compose.dev.yaml restart nomarr
```

### Reopen in Container (Dev Containers: Reopen in Container)

VS Code reconnects to the already-running devcontainer. If containers are stopped, it starts them. Does not rebuild the image.

**When you need it:** Window was closed, reconnecting after system wake, switching VS Code windows.

### Close Remote Connection (not a container action)

Disconnects VS Code from the container but does not stop it. `shutdownAction: "stopCompose"` in `devcontainer.json` means closing the VS Code window **stops the entire compose stack** (both `nomarr-dev` and `nomarr-arangodb-dev`). Container stop is graceful (`stop_grace_period: 30s`).

---

## Container Startup & Health

### Startup sequence

`nomarr-dev` has a `depends_on` condition requiring `nomarr-arangodb-dev` to be healthy before `nomarr-dev` starts. The sequence is:

1. `nomarr-arangodb-dev` starts → waits up to 130s total (30s start period + 10 retries × 10s)  
   Healthcheck: `arangosh` JS command that connects and runs `db._version()`
2. Once ArangoDB is healthy, `nomarr-dev` starts → waits up to 180s total (60s start period + 12 retries × 10s)  
   Healthcheck: `curl -sf http://127.0.0.1:8356/info`

**Total cold-start time:** Up to 5 minutes. A large `arangodb-data/` directory makes ArangoDB slower to start. This is normal — wait the full window before declaring failure.

### Expected timing on first run (empty DB)

| Milestone | Typical time |
| --- | --- |
| ArangoDB healthy | 30–60s |
| Nomarr started | 60–90s after ArangoDB |
| `/info` endpoint responding | Up to 120s total |

### Expected timing after schema migration

First start after a migration runs DB schema changes. Nomarr logs will show migration activity. Allow an extra 30–60s.

---

## Container Introspection

Container names: `nomarr-dev`, `nomarr-arangodb-dev`. Confirm with `docker ps --format '{{.Names}}'` before running other commands.

The agent has no dedicated MCP tool for containers. Use `docker` CLI via `run_in_terminal`.

**Note on interactive mode:** `docker exec -it` requires a real TTY which `run_in_terminal` on Windows does not provide. Use single-shot `docker exec <container> <cmd>` or multi-command `docker exec <container> bash -c "cmd1 && cmd2"` instead.

**Note on user context:** `devcontainer.json` sets `remoteUser: "appuser"`. VS Code runs as `appuser` inside the container. One-shot `docker exec` defaults to the container's CMD user (also `appuser` in this image). If you exec as root inadvertently and write files to a bind-mounted path, they may become inaccessible to the running service. Use `docker exec -u appuser nomarr-dev ...` if uncertain.

### Discovery — what's running

```powershell
# Running containers: name, image, status, ports
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# Include stopped containers (useful when compose up failed)
docker ps -a --format 'table {{.Names}}\t{{.Status}}'

# Compose-aware view showing health state
docker compose -f .devcontainer/docker-compose.dev.yaml ps
```

### Why did `compose up` fail?

`compose up` exit code 1 means at least one service failed to become healthy or its container exited. Diagnose in this priority order:

```powershell
# 1. Which service failed and what state is it in?
docker compose -f .devcontainer/docker-compose.dev.yaml ps

# 2. Recent log output from the failing service
docker logs nomarr-dev --tail 200
docker logs nomarr-arangodb-dev --tail 100

# 3. Healthcheck probe history (last 3 runs) — tells you what the probe actually saw
docker inspect nomarr-dev --format '{{json .State.Health}}' | ConvertFrom-Json | Select-Object -ExpandProperty Log -Last 3

# 4. Exit code, OOM flag, and error string
#    ExitCode 137 = OOM killed, 139 = segfault, 143 = SIGTERM, 1 = process error
docker inspect nomarr-dev --format 'ExitCode={{.State.ExitCode}} OOMKilled={{.State.OOMKilled}} Error={{.State.Error}}'
```

Common causes in priority order:
1. **GPU not available** — `could not select device driver "nvidia"` in compose output. Fix: install NVIDIA Container Toolkit, or the machine has no NVIDIA GPU.
2. **ArangoDB not healthy** — nomarr-dev never starts because its `depends_on` condition is not met. Check `docker logs nomarr-arangodb-dev`.
3. **Missing env file** — compose fails immediately with `env file ... not found`. Create from templates (see Env File Bootstrap section).
4. **Port already in use** — `bind: address already in use` for 8356 or 8529. Find and stop the conflicting process.
5. **Config error in nomarr** — check `docker logs nomarr-dev` for Python tracebacks or `validate_environment()` failures.

### What's actually inside the running container?

```powershell
# Process tree — confirms the app is running and what workers exist
docker exec nomarr-dev ps -ef

# Effective environment — .env file values land here; check ARANGO_HOST is set correctly
docker exec nomarr-dev env

# Installed Python packages (useful to confirm a dependency is present)
docker exec nomarr-dev python -m pip list --format=freeze

# Verify a specific module resolves from the bind mount (not a stale image layer)
docker exec nomarr-dev python -c "import nomarr; print(nomarr.__file__)"

# Disk usage — catch a full /tmp or /app/config
docker exec nomarr-dev df -h

# Read a generated file the host cannot see
docker exec nomarr-dev cat /app/config/config.yaml
```

### Filesystem state — mounts vs image layers

```powershell
# Mount inventory — confirms bind mounts are wired correctly
docker inspect nomarr-dev --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

# Confirm the live bind mount matches host source (hashes must match)
docker exec nomarr-dev sha256sum /app/nomarr/app.py
Get-FileHash .\nomarr\app.py -Algorithm SHA256
```

### Resource pressure

```powershell
# One-shot CPU/memory snapshot for all running containers
docker stats --no-stream

# GPU visibility inside nomarr-dev (should show the reserved GPU)
docker exec nomarr-dev nvidia-smi
```

### Live editing — pick up Python changes without a full rebuild

The compose mounts `../nomarr` into `/app/nomarr`. Edits on the host are immediately visible inside the container. **Nomarr does not use uvicorn `--reload`**, so changes only take effect after the process restarts:

```powershell
# Restart nomarr-dev only; nomarr-arangodb-dev is unaffected
docker compose -f .devcontainer/docker-compose.dev.yaml restart nomarr

# Follow logs to confirm clean startup
docker logs -f nomarr-dev
```

Do not use `docker compose restart nomarr` from a directory other than the repo root — the `-f` flag is required to locate the correct compose file.

### Shell access for multi-step exploration

When a series of commands is needed and constructing one-liners becomes unwieldy:

```powershell
# Non-interactive multi-command (preferred for agent use — no TTY needed)
docker exec nomarr-dev bash -c "ls /app/config && cat /app/config/config.yaml"

# Interactive shell (for human use at a real terminal — requires TTY)
docker exec -it nomarr-dev /bin/bash
```

Prefer one-shot `docker exec` over interactive sessions when running from `run_in_terminal`. Interactive TTY sessions cannot be driven reliably from the agent.

---

## Nomarr API Auth

```powershell
$login = Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/authentication/login" -Method Post `
  -ContentType "application/json" -Body '{"password":"<admin_password>"}'
$token = $login.session_token
$headers = @{Authorization="Bearer $token"}

# Example authenticated request
Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/calibration/generate-histogram" `
  -Method Post -Headers $headers
```

The `/info` endpoint is **unauthenticated** and serves as the healthcheck probe. Use it to confirm the server is up before authenticating:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8356/info"
```

---

## ArangoDB Direct Queries

```powershell
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("root:nomarr_dev_password"))

# Single query
$body = @{query='FOR doc IN libraries RETURN doc'} | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post `
  -Body $body -ContentType "application/json" -Headers @{Authorization="Basic $auth"}
$r.result | ConvertTo-Json -Depth 5

# Batch queries
$queries = @(
  "RETURN LENGTH(library_files)"
  "RETURN LENGTH(tags)"
  "RETURN LENGTH(song_has_tags)"
  "FOR lib IN libraries RETURN { name: lib.name, scan_status: lib.scan_status }"
)
foreach ($q in $queries) {
  Write-Host "=== $q ==="
  $body = @{query=$q} | ConvertTo-Json
  $r = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post `
    -Body $body -ContentType "application/json" -Headers @{Authorization="Basic $auth"}
  $r.result | ConvertTo-Json -Depth 5
}
```

**Performance expectations:**

- `song_has_tags` (~200k+ docs) / `tags` (~30k+ docs) queries: 5–30+ seconds
- Full-table scans (orphaned edge checks): 30–60+ seconds
- Calibration generation: 30–120 seconds
- **Always set 60–120s timeouts** for `Invoke-RestMethod` and `run_in_terminal`
- Never assume a query failed because it was slow — check with longer timeouts first

---

## Collection Schema

- `libraries` — library config and scan state
- `library_files` — scanned audio files (one doc per file)
- `tags` — tag vertices `{name, value}` (e.g. `{name: "artist", value: "Beatles"}`)
- `song_has_tags` — edges `library_files/*` → `tags/*`
- `library_folders` — folder-level cache for quick scan skipping
- `calibration_state`, `calibration_history` — calibration data
- `sessions` — auth sessions
- `meta` — schema version and app config

**No separate `songs`, `artists`, or `albums` collections.** Browse/entity data comes from `tags` filtered by `name`.

---

## Useful AQL Snippets

```aql
// List all collections
RETURN COLLECTIONS()[*].name

// Collection counts
RETURN LENGTH(library_files)

// Tag names by frequency
FOR t IN tags COLLECT name = t.name WITH COUNT INTO c SORT c DESC RETURN {name, c}

// Sample edges
FOR edge IN song_has_tags LIMIT 3 RETURN { from: edge._from, to: edge._to }

// Orphaned edge count (slow on large collections)
RETURN LENGTH(
  FOR edge IN song_has_tags
    FILTER !DOCUMENT(edge._from)
    RETURN 1
)
```

---

## When to Escalate to the User

Keep digging without asking when:

- Logs clearly point to a config or code error you can fix
- Healthcheck timing out but service is starting normally (often just slow init — wait the full window)
- Missing or mismatched bind mount path visible in `docker inspect`

Ask the user before:

- Wiping `.devcontainer/arangodb-data/` (destroys local database state)
- Wiping `.devcontainer/config/` (destroys Nomarr config and generated credentials)
- Running `docker compose down -v` (removes named volumes)
- Running `docker system prune` (host-wide, affects all Docker projects)
- Rebuilding the image when the failure cause is unknown (each rebuild takes minutes; diagnose first)
