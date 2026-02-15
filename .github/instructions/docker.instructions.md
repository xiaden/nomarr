# Docker Development Environment

Use `.docker/compose.yaml` to run containerized test environment (app + ArangoDB). See `.docker/` directory for compose files and commands.

## Docker vs Native Dev

**Use Docker when:**
- Reproducing prod-reported issues not visible in native dev
- Running e2e tests with Playwright (`npx playwright test` in container)
- Testing DB migration behavior
- Verifying essentia audio analysis in prod-like environment

**Use native dev when:**
- Writing/debugging backend services (faster iteration)
- Running lint/type checks
- Unit/integration tests
- Iterating on frontend components

## Interacting with the Running Container

**Credentials & Config:**
- **Nomarr admin password**: Set in `.docker/nom-config/config.yaml` → `admin_password` field
- **ArangoDB credentials**: Set in `.docker/.env` → `ARANGO_ROOT_PASSWORD` (default: `nomarr_dev_password`)
- **Nomarr API port**: `8356` (mapped from container)
- **ArangoDB port**: `8529` (mapped from container)

**Nomarr API auth** (session-based):
```powershell
# 1. Login to get session token (password from .docker/nom-config/config.yaml → admin_password)
$login = Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/auth/login" -Method Post `
  -ContentType "application/json" -Body '{"password":"<admin_password>"}'
$token = $login.session_token

# 2. Use token for authenticated requests
$headers = @{Authorization="Bearer $token"}
Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/calibration/generate-histogram" `
  -Method Post -Headers $headers
```

**ArangoDB direct queries** (via HTTP API):

The ArangoDB password is in `.docker/.env` → `ARANGO_ROOT_PASSWORD`. Use basic auth with `root:<password>`.

```powershell
# Setup auth (reuse across queries)
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("root:nomarr_dev_password"))

# Single query
$q = 'FOR doc IN libraries RETURN doc'
$body = @{query=$q} | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post `
  -Body $body -ContentType "application/json" -Headers @{Authorization="Basic $auth"}
$r.result | ConvertTo-Json -Depth 5
```

```powershell
# Batch multiple queries (useful for investigating DB state)
$queries = @(
  "RETURN LENGTH(library_files)"
  "RETURN LENGTH(tags)"
  "RETURN LENGTH(song_tag_edges)"
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

**IMPORTANT: Query and API performance expectations:**
- AQL queries against `song_tag_edges` (~200k+ docs) or `tags` (~30k+ docs) are **not instant** — expect 5-30+ seconds
- Full-table scans (e.g., orphaned edge checks) can take 30-60+ seconds
- Calibration generation scans all edges and takes 30-120 seconds depending on data volume
- API calls that trigger background work (calibration, scanning) return quickly but the work continues in-container
- **Always set generous timeouts** (60-120s minimum) for `Invoke-RestMethod` and `run_in_terminal` when running DB queries
- **Never assume a query failed because it didn't return instantly** — check with longer timeouts before investigating

**CRITICAL: Use `127.0.0.1` not `localhost`** — On Windows, `localhost` resolves to IPv6 (`::1`) first. Docker only binds IPv4, so `localhost` connections hang ~21 seconds before falling back. Always use `127.0.0.1` for both Nomarr API and ArangoDB.

## Key Collections

- `libraries` — library config and scan state
- `library_files` — scanned audio files (one doc per file)
- `tags` — tag vertices with `{rel, value}` (e.g. `{rel: "artist", value: "Beatles"}`)
- `song_tag_edges` — edges from `library_files/*` → `tags/*` (edge `_from` = file, `_to` = tag)
- `library_folders` — folder-level cache for quick scan skipping
- `calibration_state`, `calibration_history` — calibration data
- `sessions` — auth sessions
- `meta` — schema version and app config

There are **no** separate `songs`, `artists`, or `albums` collections. Browse/entity data comes from `tags` filtered by `rel` (e.g. `rel="artist"`).

## Useful Investigative Queries

```aql
-- List all collections
RETURN COLLECTIONS()[*].name

-- Check collection counts
RETURN LENGTH(library_files)

-- See unique tag rels
FOR t IN tags COLLECT rel = t.rel WITH COUNT INTO c SORT c DESC RETURN {rel, c}

-- Sample edges to verify direction
FOR edge IN song_tag_edges LIMIT 3 RETURN { from: edge._from, to: edge._to }

-- Find orphaned edges (pointing to deleted files)
RETURN LENGTH(
  FOR edge IN song_tag_edges
    FILTER !DOCUMENT(edge._from)
    RETURN 1
)
```
