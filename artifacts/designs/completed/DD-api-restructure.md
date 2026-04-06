# API Restructure: Full Endpoint Standardization — Design Document

**Status:** Completed  
**Author:** RnD-DDAuthor  
**Created:** 2026-04-05  

**Related Documents:**
- [DD-api-endpoint-cleanup (incremental fixes — now superseded by this full restructure)](artifacts/designs/pending/DD-api-endpoint-cleanup.md) — 
- [DD-ml-pipeline-automation (reconcile-tags → write-tag, reconcile-status deletion, pipeline endpoint)](artifacts/designs/pending/DD-ml-pipeline-automation.md) — 
- [ADR-006: Runtime Imports for FastAPI Depends Types](artifacts/decisions/ADR-006-runtime-imports-for-fastapi-depends-types.md) — 
- [ADR-012: Server-Side Pagination](artifacts/decisions/ADR-012-server-side-pagination-for-tag-editor-results.md) — 
- [ADR-013: TaggingService Owns Tags Vertical](artifacts/decisions/ADR-013-expand-taggingservice-as-full-tags-vertical-slice.md) — 

---

## Scope

All API endpoints across nomarr/interfaces/api/ (V1 + Web), frontend/src/shared/api/, and associated type/service contracts. Covers 108 existing endpoints — renaming, deleting, merging, moving, and fixing bugs to produce a consistent 96-endpoint API. Supersedes DD-api-endpoint-cleanup.

---

## Problem Statement

Nomarr's API has grown organically to 108 endpoints across 19 router files with no formal naming convention. Current inconsistencies include:

1. **Plural/singular mix**: `/libraries` vs `/calibration` vs `/vectors` vs `/metadata`
2. **Dead endpoints**: 8 endpoints with no callers (v1 admin pause/resume/calibration-run, calibration history/convergence/histogram-per-head, processing/status), plus 1 duplicate-bug delete (cleanup-entities) and 1 overlap-driven delete (reconcile-status per DD-ml-pipeline-automation)
3. **Duplicated state endpoints**: calibration has separate `-status` and `-progress` endpoints that should be merged (4→2)
4. **Misplaced endpoints**: `POST /worker/restart` restarts the server (not a worker), `GET /work-status` tracks ML pipeline state but lives under info router, `GET /libraries/recent-activity` is ML activity not library CRUD
5. **Known bugs**: `POST /libraries/{id}/reconcile` silently drops `library_id`, `POST /libraries/files/by-tag` has broken pagination total
6. **Layer violations**: `GET /libraries/{id}/vector-stats` orchestrates 3 services in the interface handler, `DELETE /libraries/{id}` performs file-watcher work in the handler
7. **Overloaded router**: `library_if.py` has 28 endpoints spanning CRUD, scans, file queries, tag operations, vector config, cleanup, and error handling
8. **No codified convention**: No ADR or standard governs endpoint naming

This creates maintenance burden, confusing API documentation, and makes it hard for frontend developers to predict URL patterns.

---

## Architecture

## Naming Convention Standard

### Rules

| Aspect | Convention | Example |
|--------|-----------|---------|
| URL segments | **kebab-case, full words — no abbreviations** | `/vram-probe`, `/write-mode`, `/machine-learning`, `/file-system` |
| Resource nouns | **always singular** | `/library`, `/model`, `/vector`, `/tag` |
| Collection listing | HTTP method differentiates | `GET /library` = list, `GET /library/{id}` = get one |
| Actions | explicit verb sub-paths | `POST /library/{id}/scan/quick`, `POST /calibration/apply/start` |
| Query params | **snake_case** | `?page_size=20&library_id=abc` |
| API prefix | keep `/api/v1/` and `/api/web/` split | different auth models |

### Singular Rule Scope

Singularize **resource entity nouns** in URL paths:
- `libraries` → `library`, `models` → `model`, `vectors` → `vector`
- `files` → `file`, `tags` → `tag`, `playlists` → `playlist`
- `templates` → `template`, `albums` → `album`, `artists` → `artist`
- `songs` → `song`, `outputs` → `output`, `backbones` → `backbone`

**Clarifications:**
- Process/domain groups use their natural name — `/analytics`, `/authentication`, `/tag-curation`, `/calibration`, `/playlist-import` — these are not plurals, no singularization needed
- Sub-path report names: `stats`, `tag-frequencies`, `mood-distribution`, etc. — these describe data, not entities
- `/metadata/{collection}` — the `{collection}` path parameter takes plural values (`artists`, `albums`, `labels`, `genres`, `years`), but this is a **parameterized path**, not a resource plural. The plural appears in the runtime value, not in the URL template. No convention violation.

### Router Prefix Mapping

| Old Prefix | New Prefix | Rationale |
|------------|-----------|-----------|
| `/libraries` | `/library` | Singular resource |
| `/vectors` | `/vector` | Singular resource |
| `/tags` | `/tag` | Singular resource |
| `/calibration` | `/calibration` | Already singular |
| `/analytics` | `/analytics` | Domain term exception |
| `/ml` | `/machine-learning` | Full word, no abbreviation |
| `/navidrome` | `/navidrome` | Already singular |
| `/metadata` | `/metadata` | Already singular |
| `/auth` | `/authentication` | Full word, no abbreviation |
| `/config` | `/config` | Already singular |
| `/fs` | `/file-system` | Full word, no abbreviation |
| `/api-key` | `/api-key` | Already singular compound |
| `/tag-curation` | `/tag-curation` | Process noun |
| `/playlist-import` | `/playlist-import` | Process noun |
| `/worker` | *(deleted)* | Endpoint moves to `/admin` |
| `/processing` | *(deleted)* | Endpoint deleted |
| *(none — info_if)* | *(unchanged)* | Empty prefix stays |

### New Router: `/admin`

Created to hold server management actions. Absorbs `POST /worker/restart` as `POST /admin/restart`.

---

## Complete Endpoint Mapping Table

### Legend

| Action | Meaning |
|--------|---------|
| UNCHANGED | URL stays the same |
| RENAME | URL changes (singular/kebab-case/grouping) |
| MOVE | Endpoint moves to a different router |
| MERGE | Two endpoints consolidated into one |
| DELETE | Endpoint removed |
| FIX | Bug fix applied (may also RENAME) |

---

### V1 Integration API (`/api/v1/*`) — 7→4

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 1 | GET | `/api/v1/info` | `/api/v1/info` | UNCHANGED | |
| 2 | POST | `/api/v1/admin/worker/pause` | — | DELETE | Dead, no callers |
| 3 | POST | `/api/v1/admin/worker/resume` | — | DELETE | Dead, no callers |
| 4 | POST | `/api/v1/admin/calibration/run` | — | DELETE | Web has async equivalent via `/calibration/histogram/start` + `/calibration/apply/start` |
| 5 | POST | `/api/v1/navidrome/similar-tracks` | `/api/v1/navidrome/similar-track` | RENAME | Singular |
| 6 | POST | `/api/v1/navidrome/scrobble` | `/api/v1/navidrome/scrobble` | UNCHANGED | |
| 7 | POST | `/api/v1/navidrome/generate-playlists` | `/api/v1/navidrome/playlist/generate` | RENAME | Singular + grouped |

---

### Web Authentication (`/api/web/authentication/*`) — 2→2

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 8 | POST | `/auth/login` | `/authentication/login` | RENAME |
| 9 | POST | `/auth/logout` | `/authentication/logout` | RENAME |

---

### Web Admin (`/api/web/admin/*`) — NEW ROUTER (1 endpoint)

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 10 | POST | `/worker/restart` | `/admin/restart` | MOVE | Restarts the API server, not a "worker" — belongs under admin |

---

### Web Analytics (`/api/web/analytics/*`) — 6→6

All already kebab-case. Sub-paths are analytics report names, not resource entities — no singularization needed.

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 11 | GET | `/analytics/tag-frequencies` | `/analytics/tag-frequencies` | UNCHANGED |
| 12 | GET | `/analytics/mood-distribution` | `/analytics/mood-distribution` | UNCHANGED |
| 13 | GET | `/analytics/tag-correlations` | `/analytics/tag-correlations` | UNCHANGED |
| 14 | POST | `/analytics/tag-co-occurrences` | `/analytics/tag-co-occurrences` | UNCHANGED |
| 15 | GET | `/analytics/collection-overview` | `/analytics/collection-overview` | UNCHANGED |
| 16 | GET | `/analytics/mood-analysis` | `/analytics/mood-analysis` | UNCHANGED |

---

### Web API Key (`/api/web/api-key/*`) — 2→2

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 17 | GET | `/api-key` | `/api-key` | UNCHANGED |
| 18 | POST | `/api-key/regenerate` | `/api-key/regenerate` | UNCHANGED |

---

### Web Calibration (`/api/web/calibration/*`) — 13→7

Deleted: 4 dead endpoints. Merged: 2 pairs (status+progress). Grouped actions under `apply/` and `histogram/` sub-paths.

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 19 | DELETE | `/calibration` | `/calibration` | UNCHANGED | Clear calibration data |
| 20 | GET | `/calibration/status` | `/calibration/status` | UNCHANGED | Overall calibration status |
| 21 | GET | `/calibration/histogram` | `/calibration/histogram` | UNCHANGED | Get all histogram data |
| 22 | POST | `/calibration/start-histogram` | `/calibration/histogram/start` | RENAME | Grouped under histogram/ |
| 23 | GET | `/calibration/histogram-status` | `/calibration/histogram/status` | MERGE+RENAME | Merge histogram-status + histogram-progress |
| 24 | GET | `/calibration/histogram-progress` | — | MERGE | Absorbed into `/calibration/histogram/status` |
| 25 | POST | `/calibration/start-apply` | `/calibration/apply/start` | RENAME | Grouped under apply/ |
| 26 | GET | `/calibration/apply-status` | `/calibration/apply/status` | MERGE+RENAME | Merge apply-status + apply-progress |
| 27 | GET | `/calibration/apply-progress` | — | MERGE | Absorbed into `/calibration/apply/status` |
| 28 | GET | `/calibration/history` | — | DELETE | Dead, legacy collection |
| 29 | GET | `/calibration/history/{calibration_key}` | — | DELETE | Dead, legacy collection |
| 30 | GET | `/calibration/convergence` | — | DELETE | Deprecated, no backend value |
| 31 | GET | `/calibration/histogram/{model_key}/{head_name}/{label}` | — | DELETE | No callers, overly specific |

**Merge specification for status endpoints:**
- The merged `/calibration/histogram/status` returns a single response containing: `is_running`, `progress_percent`, `current_step`, `total_steps`, `started_at`, `error` (union of fields from both old endpoints)
- Same for `/calibration/apply/status`

---

### Web Config (`/api/web/config/*`) — 2→2

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 32 | GET | `/config` | `/config` | UNCHANGED |
| 33 | POST | `/config` | `/config` | UNCHANGED |

---

### Web Filesystem (`/api/web/file-system/*`) — 1→1

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 34 | GET | `/fs/list` | `/file-system/list` | RENAME |

---

### Web Info & Health (`/api/web/*` — empty prefix router) — 4→3

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 35 | GET | `/info` | `/info` | UNCHANGED | |
| 36 | GET | `/health` | `/health` | UNCHANGED | |
| 37 | GET | `/health/gpu` | `/health/gpu` | UNCHANGED | |
| 38 | GET | `/work-status` | — | MOVE | → `/machine-learning/work-status` (tracks ML pipeline state) |

---

### Web Library (`/api/web/library/*`) — 28→25

Prefix rename: `/libraries` → `/library`. Sub-resource singularization: `files` → `file`, `tags` → `tag`. Coordinates with DD-ml-pipeline-automation for reconcile-tags → write-tag rename and reconcile-status deletion.

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 39 | GET | `/libraries` | `/library` | RENAME | List libraries |
| 40 | POST | `/libraries` | `/library` | RENAME | Create library |
| 41 | GET | `/libraries/{id}` | `/library/{id}` | RENAME | Get library |
| 42 | PATCH | `/libraries/{id}` | `/library/{id}` | RENAME | Update library |
| 43 | DELETE | `/libraries/{id}` | `/library/{id}` | RENAME+FIX | Fix layer violation: extract file-watcher stop to service method |
| 44 | GET | `/libraries/stats` | `/library/stats` | RENAME | |
| 45 | GET | `/libraries/recent-activity` | — | MOVE | → `/machine-learning/recent-activity` (ML pipeline activity, not library CRUD) |
| 46 | GET | `/libraries/files/search` | `/library/file/search` | RENAME | |
| 47 | POST | `/libraries/files/by-ids` | `/library/file/by-ids` | RENAME | |
| 48 | POST | `/libraries/files/by-tag` | `/library/file/by-tag` | RENAME+FIX | Fix broken pagination total — must use real total from DB, not `len(results)` |
| 49 | GET | `/libraries/files/tags/unique-keys` | `/library/file/tag/unique-keys` | RENAME | |
| 50 | GET | `/libraries/files/tags/values` | `/library/file/tag/values` | RENAME | |
| 51 | GET | `/libraries/files/tags/mood-values` | `/library/file/tag/mood-values` | RENAME | |
| 52 | GET | `/libraries/files/{file_id}/tags` | `/library/file/{file_id}/tag` | RENAME | |
| 53 | POST | `/libraries/cleanup-tags` | `/library/cleanup-tag` | RENAME | |
| 54 | POST | `/libraries/cleanup-entities` | — | DELETE | Duplicate of cleanup-tags |
| 55 | POST | `/libraries/{id}/scan/quick` | `/library/{id}/scan/quick` | RENAME | |
| 56 | POST | `/libraries/{id}/scan/full` | `/library/{id}/scan/full` | RENAME | |
| 57 | POST | `/libraries/{id}/reconcile` | `/library/{id}/reconcile` | RENAME+FIX | Fix: `library_id` from path currently silently dropped — must be passed to service |
| 58 | POST | `/libraries/{id}/reconcile-tags` | `/library/{id}/write-tag` | RENAME | Per DD-ml-pipeline-automation: reconcile-tags → write-tag |
| 59 | GET | `/libraries/{id}/reconcile-status` | — | DELETE | Per DD-ml-pipeline-automation: replaced by pipeline status |
| 60 | PATCH | `/libraries/{id}/write-mode` | `/library/{id}/write-mode` | RENAME | |
| 61 | POST | `/libraries/{id}/validate-tags` | `/library/{id}/validate-tag` | RENAME | |
| 62 | GET | `/libraries/{id}/vector-config` | `/library/{id}/vector-config` | RENAME | |
| 63 | PUT | `/libraries/{id}/vector-config` | `/library/{id}/vector-config` | RENAME | |
| 64 | GET | `/libraries/{id}/vector-stats` | `/library/{id}/vector-stats` | RENAME+FIX | Fix layer violation: extract multi-service orchestration to service method |
| 65 | GET | `/libraries/{id}/errored-files` | `/library/{id}/errored-file` | RENAME | |
| 66 | POST | `/libraries/{id}/retry-errored` | `/library/{id}/retry-errored` | RENAME | |

---

### Web Metadata (`/api/web/metadata/*`) — 6→6

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 67 | GET | `/metadata/counts` | `/metadata/count` | RENAME | Singular |
| 68 | GET | `/metadata/{collection}` | `/metadata/{collection}` | UNCHANGED | |
| 69 | GET | `/metadata/{collection}/{id}` | `/metadata/{collection}/{id}` | UNCHANGED | |
| 70 | GET | `/metadata/{collection}/{id}/songs` | `/metadata/{collection}/{id}/song` | RENAME | Singular |
| 71 | GET | `/metadata/albums/{id}/artists` | `/metadata/album/{id}/artist` | RENAME | Singular |
| 72 | GET | `/metadata/artists/{id}/albums` | `/metadata/artist/{id}/album` | RENAME | Singular |

---

### Web Machine Learning (`/api/web/machine-learning/*`) — 5→7

Absorbs `work-status` from info router and `recent-activity` from library router.

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 73 | GET | `/ml/models` | `/machine-learning/model` | RENAME | Singular + full word prefix |
| 74 | GET | `/ml/models/{id}/outputs` | `/machine-learning/model/{id}/output` | RENAME | Singular + full word prefix |
| 75 | PATCH | `/ml/models/{id}/outputs/{output_id}` | `/machine-learning/model/{id}/output/{output_id}` | RENAME | Singular + full word prefix |
| 76 | POST | `/ml/models/{id}/mark-configured` | `/machine-learning/model/{id}/mark-configured` | RENAME | Singular + full word prefix |
| 77 | POST | `/ml/vram-probe` | `/machine-learning/vram-probe` | RENAME | Full word prefix |
| 78 | GET | `/work-status` | `/machine-learning/work-status` | MOVE | From info_if empty-prefix router |
| 79 | GET | `/libraries/recent-activity` | `/machine-learning/recent-activity` | MOVE | ML pipeline activity, not library CRUD |

---

### Web Navidrome (`/api/web/navidrome/*`) — 12→12

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 80 | GET | `/navidrome/preview` | `/navidrome/preview` | UNCHANGED | |
| 81 | GET | `/navidrome/tag-values` | `/navidrome/tag-value` | RENAME | Singular |
| 82 | GET | `/navidrome/config` | `/navidrome/config` | UNCHANGED | |
| 83 | POST | `/navidrome/playlists/preview` | `/navidrome/playlist/preview` | RENAME | Singular |
| 84 | POST | `/navidrome/playlists/generate` | `/navidrome/playlist/generate` | RENAME | Singular |
| 85 | GET | `/navidrome/templates` | `/navidrome/template` | RENAME | Singular |
| 86 | POST | `/navidrome/templates` | `/navidrome/template` | RENAME | Singular |
| 87 | POST | `/navidrome/playlists/static` | `/navidrome/playlist/static` | RENAME | Singular |
| 88 | POST | `/navidrome/playlists/push` | `/navidrome/playlist/push` | RENAME | Singular |
| 89 | POST | `/navidrome/sync-songs` | `/navidrome/sync-song` | RENAME | Singular; frontend caller in navidrome.ts |
| 90 | POST | `/navidrome/ping` | `/navidrome/ping` | UNCHANGED | Health-check style action verb |
| 91 | GET | `/navidrome/status` | `/navidrome/status` | UNCHANGED | Navidrome connection status |

---

### Web Playlist Import (`/api/web/playlist-import/*`) — 2→2

| # | Method | Old URL | New URL | Action |
|---|--------|---------|---------|--------|
| 92 | POST | `/playlist-import/convert` | `/playlist-import/convert` | UNCHANGED |
| 93 | GET | `/playlist-import/spotify-status` | `/playlist-import/spotify-status` | UNCHANGED |

---

### Web Processing (`/api/web/processing/*`) — 1→0

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 94 | GET | `/processing/status` | — | DELETE | Superseded by `GET /machine-learning/work-status` |

---

### Web Tag Curation (`/api/web/tag-curation/*`) — 8→8

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 95 | POST | `/tag-curation/rename` | `/tag-curation/rename` | UNCHANGED | |
| 96 | POST | `/tag-curation/merge` | `/tag-curation/merge` | UNCHANGED | |
| 97 | POST | `/tag-curation/split` | `/tag-curation/split` | UNCHANGED | |
| 98 | GET | `/tag-curation/values` | `/tag-curation/value` | RENAME | Singular |
| 99 | GET | `/tag-curation/{tag_id}/songs` | `/tag-curation/{tag_id}/song` | RENAME | Singular |
| 100 | POST | `/tag-curation/commit` | `/tag-curation/commit` | UNCHANGED | |
| 101 | GET | `/tag-curation/pending-count` | `/tag-curation/pending-count` | UNCHANGED | |
| 102 | PATCH | `/tag-curation/files/{file_id}/tags` | `/tag-curation/file/{file_id}/tag` | RENAME | Singular |

---

### Web Tags (`/api/web/tag/*`) — 2→2

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 103 | GET | `/tags/show-tags` | `/tag/show` | RENAME | Singular prefix + remove redundant `-tags` suffix |
| 104 | DELETE | `/tags/remove-tags` | `/tag/remove` | RENAME | Singular prefix + remove redundant `-tags` suffix |

---

### Web Vectors (`/api/web/vector/*`) — 6→6

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| 105 | GET | `/vectors/backbones` | `/vector/backbone` | RENAME | Singular |
| 106 | POST | `/vectors/search` | `/vector/search` | RENAME | |
| 107 | GET | `/vectors/track` | `/vector/track` | RENAME | |
| 108 | GET | `/vectors/stats` | `/vector/stats` | RENAME | |
| 109 | POST | `/vectors/promote` | `/vector/promote` | RENAME | |
| 110 | POST | `/vectors/rebuild-index` | `/vector/rebuild-index` | RENAME | |

---

### Web Worker (`/api/web/worker/*`) — 1→0 (moved to admin)

| # | Method | Old URL | New URL | Action | Notes |
|---|--------|---------|---------|--------|-------|
| — | POST | `/worker/restart` | — | MOVE | See Web Admin section (#10) |

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| Endpoints before | 108 |
| Deleted | 10 |
| Merged (4→2) | -2 |
| **Endpoints after** | **96** |
| Renamed (URL changed) | 62 |
| Moved to different router | 3 |
| Bug-fixed | 2 |
| Layer-violation-fixed | 2 |
| Unchanged | 31 |
| Routers removed | 2 (processing_if.py, worker_if.py) |
| Routers added | 1 (admin_if.py) |

### Deletion Breakdown

| Category | Count | Endpoints |
|----------|-------|-----------|
| Dead (no callers) | 8 | v1 admin pause, v1 admin resume, v1 admin calibration/run, calibration/history, calibration/history/{key}, calibration/convergence, calibration/histogram/{m}/{h}/{l}, processing/status |
| Duplicate-bug delete | 1 | libraries/cleanup-entities (duplicate of cleanup-tags) |
| Overlap-driven delete | 1 | libraries/{id}/reconcile-status (replaced by pipeline status per DD-ml-pipeline-automation) |
| **Total deleted** | **10** | |

---

## Bug Fixes

### BUG-1: `POST /library/{id}/reconcile` — library_id silently dropped

**Current behavior:** The `library_id` path parameter is accepted but not passed to the service call. The reconcile operation runs globally instead of per-library.

**Fix:** Pass `library_id` to `LibraryService.reconcile_library_paths(library_id=library_id)`. Verify the service and downstream workflow accept and filter by library_id.

### BUG-2: `POST /library/file/by-tag` — broken pagination total

**Current behavior:** Response `total` field is set to `len(files)` after limiting, so pagination consumers cannot trust the total. Violates ADR-012 (server-side pagination must return real total/rowCount).

**Fix:** Query the real total count from the database (separate count query or use AQL `COLLECT WITH COUNT`) and return it in the response. Ensure the service method returns both the page of results and the total count.

### BUG-3: `DELETE /library/{id}` — layer violation (file watcher in handler)

**Current behavior:** The interface handler directly stops file watchers as part of deletion. This is orchestration logic that belongs in the service layer.

**Fix:** Extract the file-watcher stop + library deletion into a single `LibraryService.delete_library(library_id)` method that handles both. Interface just calls the one service method.

### BUG-4: `GET /library/{id}/vector-stats` — layer violation (multi-service orchestration)

**Current behavior:** The interface handler calls 3 different service methods and assembles the response. This is orchestration that violates the one-service-call rule.

**Fix:** Create a single `VectorService.get_library_vector_stats(library_id)` (or extend existing service) that returns the assembled stats. Interface calls one method.

---

## Merge Specifications

### MERGE-1: Calibration Apply Status

**Old endpoints:**
- `GET /calibration/apply-status` → returns `{is_running, error}`
- `GET /calibration/apply-progress` → returns `{progress_percent, current_step, total_steps}`

**New endpoint:** `GET /calibration/apply/status`

**Response shape:**
```json
{
  "is_running": true,
  "progress_percent": 45.0,
  "current_step": 120,
  "total_steps": 267,
  "error": null
}
```

### MERGE-2: Calibration Histogram Status

**Old endpoints:**
- `GET /calibration/histogram-status` → returns `{is_running, error}`
- `GET /calibration/histogram-progress` → returns `{progress_percent, current_step, total_steps}`

**New endpoint:** `GET /calibration/histogram/status`

**Response shape:** Same as MERGE-1.

---

## Coordination with DD-ml-pipeline-automation

DD-ml-pipeline-automation (APPROVED) makes three route changes that overlap with this restructure:

| DD-ml-pipeline-automation Change | This DD's Handling |
|----------------------------------|--------------------|
| Rename `/libraries/{id}/reconcile-tags` → `/libraries/{id}/write-tags` | Absorbed: becomes `/library/{id}/write-tag` (singular applied on top) |
| Delete `GET /libraries/{id}/reconcile-status` | Absorbed: deleted here too |
| Add `GET /libraries/{id}/pipeline` | NOT in this DD — added by that DD's implementation. This DD names it `/library/{id}/pipeline` for naming consistency. |

**Implementation ordering:** This DD should execute its Phase 1-2 (deletions + bug fixes) before or independently of DD-ml-pipeline-automation. Phase 3 (renames) can run in any order relative to that DD, but the rename of `reconcile-tags` → `write-tag` must happen once, not twice.

---

## Frontend Impact

Every renamed/moved/deleted endpoint requires a corresponding frontend API client update.

### Files Requiring Updates

| Frontend File | Endpoints Affected | Change Type |
|--------------|-------------------|-------------|
| `frontend/src/shared/api/library.ts` | ~17 endpoint URLs | URL prefix `/libraries` → `/library`, sub-paths singularized |
| `frontend/src/shared/api/library.test.ts` | 2 hardcoded URLs | Has hardcoded `/libraries/{id}/reconcile-tags` and `/libraries/{id}/reconcile-status` assertions |
| `frontend/src/shared/api/files.ts` | 6 endpoints | URL prefix `/libraries/files` → `/library/file`, tag paths singularized |
| `frontend/src/shared/api/vectors.ts` | 6 endpoints | URL prefix `/vectors` → `/vector`, sub-paths singularized |
| `frontend/src/shared/api/calibration.ts` | 12 → 7 | Remove deleted endpoints, update merged URLs, restructure paths |
| `frontend/src/shared/api/ml.ts` | 5 endpoints | URL `/ml/models` → `/machine-learning/model`, sub-paths singularized |
| `frontend/src/shared/api/navidrome.ts` | 9 endpoint URLs | Plurals → singular (playlists→playlist, templates→template, sync-songs→sync-song), plus 2 unchanged (ping, status) |
| `frontend/src/shared/api/processing.ts` | 2 endpoints | Delete `/processing/status` call, move `/work-status` → `/machine-learning/work-status` |
| `frontend/src/shared/api/worker.ts` | 1 endpoint | `/worker/restart` → `/admin/restart` |
| `frontend/src/shared/api/tagCuration.ts` | ~5 renamed paths | Singularize sub-paths (values→value, songs→song, files→file, tags→tag) + commit/pending-count unchanged |
| `frontend/src/shared/api/tags.ts` | 2 endpoints | `/tags/show-tags` → `/tag/show`, `/tags/remove-tags` → `/tag/remove` |
| `frontend/src/shared/api/metadata.ts` | 5 endpoint patterns | Singularize (counts→count, songs→song, albums→album, artists→artist) + parameterized `{collection}` paths |
| `frontend/src/shared/api/analytics.ts` | 0 backend changes | UNCHANGED — but see dead function note below |
| `frontend/src/shared/api/auth.ts` | 2 endpoint URLs | `/auth/login` → `/authentication/login`, `/auth/logout` → `/authentication/logout` |
| `frontend/src/shared/api/apiKey.ts` | 0 | UNCHANGED |
| `frontend/src/shared/api/config.ts` | 0 | UNCHANGED |
| `frontend/src/shared/api/filesystem.ts` | 1 endpoint URL | `/fs/list` → `/file-system/list` |
| `frontend/src/shared/api/playlistImport.ts` | 0 | UNCHANGED |

### Frontend Deletion Checklist

Remove dead frontend functions that call deleted backend endpoints:
- Calibration: `getConvergenceStatus()`, `getCalibrationHistory()`, `getCalibrationHistorySingle()`, `getHistogramForHead()`
- Processing: `getProcessingStatus()` (if separate from work-status)
- Library: `cleanupOrphanedEntities()` (if exists)

### Dead Frontend Function

`analytics.ts` has a function calling `GET /api/web/analytics/tag-co-occurrences/{tag}` (line 85) — this route does **not exist** on the backend. The backend only exposes `POST /analytics/tag-co-occurrences` (with a request body). This dead function should be removed or fixed during the restructure.

### Route-Order Sensitivity

`/metadata/count` (renamed from `/counts`) vs `/metadata/{collection}` — static routes **must** be registered before dynamic path-parameter routes in FastAPI, or the static path will be shadowed. Current code already registers `/counts` first; after rename to `/count`, verify registration order is preserved in `metadata_if.py`.

---

## Router File Changes

### Files to Modify

| File | Changes |
|------|---------|
| `nomarr/interfaces/api/web/library_if.py` | Rename prefix to `/library`, update all paths, remove 3 endpoints, fix 2 bugs |
| `nomarr/interfaces/api/web/calibration_if.py` | Restructure paths under `apply/` and `histogram/`, delete 4 endpoints, merge 2 pairs |
| `nomarr/interfaces/api/web/ml_if.py` | Singularize paths, add `work-status` + `recent-activity` handlers |
| `nomarr/interfaces/api/web/vectors_if.py` | Rename prefix to `/vector`, singularize sub-paths |
| `nomarr/interfaces/api/web/tags_if.py` | Rename prefix to `/tag`, clean up redundant path suffixes |
| `nomarr/interfaces/api/web/navidrome_if.py` | Singularize sub-paths (playlists→playlist, templates→template) |
| `nomarr/interfaces/api/web/metadata_if.py` | Singularize sub-paths |
| `nomarr/interfaces/api/web/tag_curation_if.py` | Singularize sub-paths |
| `nomarr/interfaces/api/web/info_if.py` | Remove `work-status` handler (moved to ml_if) |
| `nomarr/interfaces/api/web/router.py` | Update include_router calls for renamed prefixes, add admin router, remove processing + worker |
| `nomarr/interfaces/api/v1/admin_if.py` | Delete file entirely (all 3 endpoints removed) |
| `nomarr/interfaces/api/v1/navidrome_v1_if.py` | Singularize paths |
| `nomarr/interfaces/api/api_app.py` | Remove v1 admin router include |

### Files to Delete

| File | Reason |
|------|--------|
| `nomarr/interfaces/api/web/processing_if.py` | Sole endpoint deleted |
| `nomarr/interfaces/api/web/worker_if.py` | Sole endpoint moved to admin |
| `nomarr/interfaces/api/v1/admin_if.py` | All endpoints deleted |

### Files to Create

| File | Purpose |
|------|---------|
| `nomarr/interfaces/api/web/admin_if.py` | New admin router with `POST /admin/restart` |

### Type Files Impact

Type files under `nomarr/interfaces/api/types/` may need renaming if router files are renamed, but since type files are named by domain (not by URL), most stay unchanged. Check:
- `types/processing.py` → delete if no types remain after endpoint deletion
- `types/worker.py` → delete or rename to `types/admin.py`

---

## Implementation Phases

### Phase 1: Delete Dead Code (10 endpoints removed)

**Scope:** Remove endpoints, handlers, and any dead service methods they exclusively serve.

**Endpoints deleted:**
1. `POST /api/v1/admin/worker/pause`
2. `POST /api/v1/admin/worker/resume`
3. `POST /api/v1/admin/calibration/run`
4. `GET /calibration/history`
5. `GET /calibration/history/{key}`
6. `GET /calibration/convergence`
7. `GET /calibration/histogram/{model_key}/{head_name}/{label}`
8. `POST /libraries/cleanup-entities`
9. `GET /processing/status`
10. `GET /libraries/{id}/reconcile-status`

**Files affected:** `admin_if.py` (delete), `calibration_if.py`, `library_if.py`, `processing_if.py` (delete), `router.py`

**Frontend cleanup:** Remove corresponding API functions from `calibration.ts`, `processing.ts`, `library.ts`

**Ordering:** Can execute independently. No dependencies.

### Phase 2: Bug Fixes (4 fixes)

**Scope:** Fix bugs and layer violations in existing handlers before renaming them.

1. **BUG-1:** Fix `reconcile_library_paths()` to pass `library_id`
2. **BUG-2:** Fix `search_files_by_tag()` pagination total
3. **BUG-3:** Extract file-watcher stop from `delete_library()` handler to service
4. **BUG-4:** Extract vector-stats orchestration from handler to service

**Ordering:** Independent of Phase 1. Can execute in parallel.

### Phase 3: Merge Calibration Endpoints (4→2)

**Scope:** Merge status+progress endpoint pairs into single status endpoints with restructured paths.

1. Merge `apply-status` + `apply-progress` → `apply/status`
2. Merge `histogram-status` + `histogram-progress` → `histogram/status`
3. Restructure `start-apply` → `apply/start`, `start-histogram` → `histogram/start`

**Ordering:** After Phase 1 (dead calibration endpoints already removed).

### Phase 4: Backend URL Restructure (52 renames + 3 moves)

**Scope:** Apply the naming convention to all remaining endpoints in a single coordinated pass.

**Sub-phases (can be done per-router or all at once):**
1. Rename router prefixes: `libraries→library`, `vectors→vector`, `tags→tag`
2. Singularize sub-paths across all routers
3. Move `work-status` from `info_if.py` to `ml_if.py`
4. Move `recent-activity` from `library_if.py` to `ml_if.py`
5. Create `admin_if.py`, move restart from `worker_if.py`
6. Delete empty routers: `worker_if.py`
7. Update `router.py` includes

**Ordering:** After Phase 2 (bugs fixed in code that's about to be renamed) and Phase 3 (merges done).

### Phase 5: Frontend URL Migration

**Scope:** Update all frontend API client files to use new URLs. Deploy lockstep with Phase 4.

**Ordering:** MUST deploy simultaneously with Phase 4. No backward compatibility layer — clean break.

### Phase 6: Cleanup & Documentation

**Scope:**
1. Delete unused type files (`types/processing.py`, `types/worker.py` if empty)
2. Update OpenAPI tags and descriptions
3. Update any documentation referencing old URLs
4. Run full lint + test suite
5. Verify no stale imports remain

**Ordering:** After Phase 5.

---

## Constraints

| Constraint | Impact |
|-----------|--------|
| Alpha software — breaking changes allowed | No backward-compat layer needed |
| No schema migrations required | This is route-level only; no DB changes |
| ADR-006: Runtime imports for Depends types | New/moved router files must import service types at runtime, not under TYPE_CHECKING |
| ADR-013: TaggingService owns tag vertical | Tag-domain endpoints must not drift back into LibraryService during reorganization |
| ADR-012: Server-side pagination | BUG-2 fix must comply — return real total count |
| DD-ml-pipeline-automation coordination | reconcile-tags→write-tag rename happens once; reconcile-status deletion coordinated |
| Frontend lockstep deployment | Backend URL changes + frontend URL changes must deploy together |

---

## Design Goals

1. **Single consistent naming convention** across all 96 endpoints — kebab-case, full words, singular entity nouns, no abbreviations
2. **Zero dead code** — remove all endpoints with no callers
3. **Fix known bugs** — reconcile library_id, by-tag pagination, layer violations
4. **Clean router organization** — each router owns a coherent domain, no overloaded mega-routers
5. **Actionable implementation plan** — an execution team can implement from this DD alone without ambiguity
6. **Coordinate with DD-ml-pipeline-automation** — no conflicting renames or deletions

---

## Constraints

- Alpha software: breaking API changes are allowed, no backward-compat shim needed
- No database migrations: all changes are route-level (paths, handlers, response shapes for merges)
- ADR-006: Router files must import service Depends types at runtime
- ADR-013: Tag operations must stay under TaggingService ownership
- ADR-012: Pagination fixes must return real totals
- Frontend must update lockstep with backend URL changes
- DD-ml-pipeline-automation overlap must be coordinated (reconcile-tags → write-tag, reconcile-status deletion)

---

## Open Questions

1. **Cross-library file search location**: Should `GET /library/file/search` (currently cross-library with optional `library_id` param) be promoted to a top-level `/file/search` resource? Currently it lives under `/library` prefix but operates cross-library. Recommendation: keep under `/library/file/` for now — it's about library files, even if the library filter is optional. Revisit if a standalone file concept emerges.

2. **`POST /analytics/tag-co-occurrences` as POST for reads**: This uses POST for what is conceptually a read operation (with a complex filter body). Should it become GET with query params? Recommendation: keep POST — the request body is too complex for query params. Document as a "query endpoint" in OpenAPI.

3. **Tag router (`/tag`) scope**: Currently has `show-tags` and `remove-tags` — utility endpoints for raw tag inspection. Should these merge into `/tag-curation`? Recommendation: keep separate — `/tag` is raw tag I/O, `/tag-curation` is the curated editing workflow. They serve different UIs.

4. **Future `/library/{id}/pipeline` naming**: DD-ml-pipeline-automation adds this endpoint. Under this naming convention it stays `/library/{id}/pipeline` (already singular, kebab-case). No conflict.

5. **V1 API scope**: Should V1 get the same singular treatment, or is it a stable external API? Recommendation: apply singular naming to V1 too — it's alpha software with only the Navidrome plugin as a known consumer, which we control.

---
