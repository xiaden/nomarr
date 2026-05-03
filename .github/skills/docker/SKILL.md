---
name: docker
description: Reference for the Nomarr Docker development environment. Use when working with Docker containers, running e2e tests, querying ArangoDB directly, debugging prod-like issues, testing DB migrations, or interacting with the containerized Nomarr API. Contains credentials, ports, PowerShell snippets, AQL queries, and collection schema.
---

# Docker Development Environment

Use `.docker/compose.yaml` to run the containerized test environment (app + ArangoDB). See `.docker/` for compose files and commands.

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

## Credentials & Ports

- **Nomarr admin password**: `.docker/nom-config/config.yaml` → `admin_password`
- **ArangoDB password**: `.docker/.env` → `ARANGO_ROOT_PASSWORD` (default: `nomarr_dev_password`)
- **Nomarr API**: `http://127.0.0.1:8356`
- **ArangoDB**: `http://127.0.0.1:8529`

**CRITICAL: Use `127.0.0.1` not `localhost`** — On Windows, `localhost` resolves to IPv6 (`::1`) first. Docker only binds IPv4, so `localhost` hangs ~21 seconds before falling back.

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

## Collection Schema

- `libraries` — library config and scan state
- `library_files` — scanned audio files (one doc per file)
- `tags` — tag vertices `{name, value}` (e.g. `{name: "artist", value: "Beatles"}`)
- `song_has_tags` — edges `library_files/*` → `tags/*`
- `library_folders` — folder-level cache for quick scan skipping
- `calibration_state`, `calibration_history` — calibration data
- `sessions` — auth sessions
- `meta` — schema version and app config

**No separate `songs`, `artists`, or `albums` collections.** Browse/entity data comes from `tags` filtered by `rel`.

## Useful AQL Snippets

```aql
-- List all collections
RETURN COLLECTIONS()[*].name

-- Collection counts
RETURN LENGTH(library_files)

-- Unique tag rels
FOR t IN tags COLLECT name = t.name WITH COUNT INTO c SORT c DESC RETURN {name, c}

-- Sample edges
FOR edge IN song_has_tags LIMIT 3 RETURN { from: edge._from, to: edge._to }

-- Orphaned edge count
RETURN LENGTH(
  FOR edge IN song_has_tags
    FILTER !DOCUMENT(edge._from)
    RETURN 1
)
```
