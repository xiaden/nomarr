# API Endpoint Cleanup and Restructuring — Design Document

**Status:** Draft  
**Author:** RnD-DDAuthor  
**Created:** 2026-04-05  

**Related Documents:**

- [ADR-006: Runtime Imports for FastAPI Depends Types](artifacts/decisions/ADR-006-runtime-imports-for-fastapi-depends-types.md) —
- [ADR-013: Expand TaggingService as Full Tags Vertical Slice](artifacts/decisions/ADR-013-expand-taggingservice-as-full-tags-vertical-slice.md) —
- [Interfaces Layer Instructions](.github/instructions/interfaces.instructions.md) —

---

## Scope

nomarr/interfaces/api/, frontend/src/shared/api/

---

## Problem Statement

The API surface has accumulated inconsistencies over iterative development:

1. **Dead v1 endpoints** — Worker pause/resume and synchronous calibration/run exist under the v1 plugin API with no known consumers. The web frontend cannot call them (session vs API-key auth mismatch). The sync calibration/run is redundant with the async web equivalent.
2. **Misplaced endpoints** — Work-status (ML processing progress) lives under the info router instead of the ML router. Recent-activity (ML tagging results) lives under the library router. Server restart lives under the worker router despite restarting the entire API process.
3. **Endpoint bloat in calibration** — 13 endpoints with overlapping status/progress pairs (histogram-status + histogram-progress, apply-status + apply-progress) that could be consolidated.
4. **Deprecated endpoint still served** — `/calibration/convergence` is marked deprecated but still has an active frontend caller.
5. **File search is not library-scoped** — `/libraries/files/search` searches across all libraries with no `library_id` parameter, inconsistent with the `POST /{library_id}/action` pattern used by scan, reconcile, etc.
6. **No formal REST naming convention** — Routes happen to use kebab-case, but there is no project ADR enforcing this or other conventions.

---

## Architecture

## Current State

### Router Mounting

All web routers mount under `/api/web` (session auth). V1 routers mount at `/api/v1` (API-key auth).

 | Router File | Prefix | Endpoint Count |
 | --- | --- | --- |
 | `analytics_if.py` | `/api/web/analytics/` | 6 |
 | `calibration_if.py` | `/api/web/calibration/` | 13 |
 | `info_if.py` | `/api/web/` (empty prefix) | 4 |
 | `library_if.py` | `/api/web/libraries/` | 23 |
 | `ml_if.py` | `/api/web/ml/` | 5 |
 | `worker_if.py` | `/api/web/worker/` | 1 |
 | `v1/admin_if.py` | `/api/v1/admin/` | 3 |

### Group-by-Group Current Endpoints

#### Group 1: v1 Worker Pause/Resume (DELETE)

- `POST /api/v1/admin/worker/pause` → `WorkerSystemService.pause`
- `POST /api/v1/admin/worker/resume` → `WorkerSystemService.resume`
- No known frontend or plugin callers. Worker pause/resume is an internal operation.

#### Group 2: v1 Calibration Run (DELETE)

- `POST /api/v1/admin/calibration/run` → `CalibrationService` + `ConfigService`
- Synchronous equivalent of `POST /api/web/calibration/start-histogram` (async/background).
- No known external callers.

#### Group 3: Analytics Endpoints (STANDARDIZE)

Current routes (all already kebab-case, consistent):

- `GET  /api/web/analytics/tag-frequencies` — limit param
- `GET  /api/web/analytics/mood-distribution` — optional library_id
- `GET  /api/web/analytics/tag-correlations` — top_n param
- `POST /api/web/analytics/tag-co-occurrences` — TagCoOccurrenceRequest body + optional library_id
- `GET  /api/web/analytics/collection-overview` — optional library_id
- `GET  /api/web/analytics/mood-analysis` — optional library_id

Frontend callers: `frontend/src/shared/api/analytics.ts` (all 6 endpoints called).

**Finding:** Routes are already well-structured. No changes needed beyond documenting as the reference pattern.

#### Group 4: Calibration Endpoints (CONSOLIDATE)

Current routes:

- `DELETE /api/web/calibration` — clear all calibration data
- `GET    /api/web/calibration/status` — per-library calibration version breakdown
- `POST   /api/web/calibration/start-histogram` — start histogram generation (background)
- `GET    /api/web/calibration/histogram-status` — generation running/completed/error
- `GET    /api/web/calibration/histogram-progress` — per-head progress (total, completed, remaining)
- `POST   /api/web/calibration/start-apply` — start apply in background
- `GET    /api/web/calibration/apply-status` — apply running/completed/error
- `GET    /api/web/calibration/apply-progress` — per-file progress (total, completed, current_file)
- `GET    /api/web/calibration/history` — all heads convergence history
- `GET    /api/web/calibration/history/{calibration_key}` — single head history
- `GET    /api/web/calibration/convergence` — **DEPRECATED** old progressive convergence
- `GET    /api/web/calibration/histogram/{model_key}/{head_name}/{label}` — histogram bins for a label
- `GET    /api/web/calibration/histogram` — all calibration states with histograms

Frontend callers: `frontend/src/shared/api/calibration.ts` (all endpoints called, including deprecated convergence).

**Proposed consolidation:**

- Merge `histogram-status` + `histogram-progress` → `GET /calibration/generate/status` (include both high-level status and per-head progress in one response)
- Merge `apply-status` + `apply-progress` → `GET /calibration/apply/status` (include both high-level status and per-file progress in one response)
- Rename `start-histogram` → `POST /calibration/generate` (clearer action naming)
- Rename `start-apply` → `POST /calibration/apply` (clearer action naming)
- Delete `convergence` endpoint (deprecated, remove frontend caller)
- Keep `status`, `history`, `history/{key}`, `histogram/{...}/{...}/{...}`, `histogram`, `DELETE /` unchanged

#### Group 5: Deprecated Convergence (DELETE)

- `GET /api/web/calibration/convergence` — Explicitly marked `deprecated=True` in FastAPI decorator.
- Frontend still calls it at `frontend/src/shared/api/calibration.ts` line 174.
- Must remove frontend caller when deleting.

#### Group 6: Work-Status (MOVE)

- Current: `GET /api/web/work-status` (info_if.py, empty router prefix)
- Returns scanning + ML processing status for frontend polling.
- **Move to:** `GET /api/web/ml/work-status`
- Frontend caller: `frontend/src/shared/api/processing.ts` line 66.

#### Group 7: Library Stats + Library List (MERGE)

- `GET /api/web/libraries` → `ListLibrariesResponse` (list of `LibraryResponse` objects)
- `GET /api/web/libraries/stats` → `LibraryStatsResponse` (total_files, unique_artists, unique_albums, total_duration_seconds)

`LibraryResponse` already includes `file_count` and `folder_count` per library. `LibraryStatsResponse` provides cross-library aggregates (unique artists, albums, total duration). These are complementary, not duplicated.

**Decision:** Merge stats into the library list response. Add an `aggregate_stats` field to `ListLibrariesResponse`. Remove `/libraries/stats` endpoint.

Frontend callers:

- List: multiple components via `frontend/src/shared/api/library.ts`
- Stats: `frontend/src/shared/api/library.ts` line 20, used in `LibraryStats.tsx` component

#### Group 8: Recent Activity (MOVE)

- Current: `GET /api/web/libraries/recent-activity` — recently tagged files, optional library_id filter
- This is ML tagging activity, not library management.
- **Move to:** `GET /api/web/ml/recent-activity`
- Frontend caller: `frontend/src/shared/api/library.ts` line 249.

#### Group 9: Per-Library vs Aggregate Stats (RATIONALIZE)

- `LibraryResponse` has `file_count`, `folder_count` (per-library)
- `LibraryStatsResponse` has `total_files`, `unique_artists`, `unique_albums`, `total_duration_seconds` (aggregate)

These are complementary. Per-library stats live on each `LibraryResponse`. Aggregate stats summarize across all libraries. **Resolved by Group 7** — merge aggregate into list response, no separate endpoint needed.

#### Group 10: File Search (SCOPE)

- Current: `GET /api/web/libraries/files/search` — searches across ALL libraries
- Parameters: q, artist, album, tag_key, tag_value, tagged_only, limit, offset
- **Add `library_id` as optional query parameter** (not path param, since the endpoint also supports cross-library search)
- Keep at current path, add optional filtering.
- Frontend caller: `frontend/src/shared/api/files.ts` line 69.

**Decision:** Adding `library_id` as optional query parameter rather than restructuring to `/{library_id}/search` preserves the cross-library use case while enabling library-scoped search.

#### Group 11: Server Restart (MOVE)

- Current: `POST /api/web/worker/restart` — restarts the entire API server
- This is an admin action, not a worker action.
- **Move to:** `POST /api/web/admin/restart`
- Requires creating a new `admin_if.py` web router with `/admin` prefix.
- Frontend caller: `frontend/src/shared/api/worker.ts` line 16.

---

## Affected Files

Complete inventory of files requiring changes, organized by layer. Files marked **(new)** do not exist yet.

### Interfaces Layer — Routers

 | File | Change Type | Group |
 | --- | --- | --- |
 | `nomarr/interfaces/api/v1/admin_if.py` | DELETE (empty after removing 3 endpoints) | Phase 1 |
 | `nomarr/interfaces/api/api_app.py` | UPDATE — remove v1 admin router mount | Phase 1 |
 | `nomarr/interfaces/api/web/calibration_if.py` | UPDATE — delete convergence, rename/merge endpoints | Phase 1, 2, 3 |
 | `nomarr/interfaces/api/web/info_if.py` | UPDATE — remove work-status handler | Phase 2 |
 | `nomarr/interfaces/api/web/library_if.py` | UPDATE — remove recent-activity + stats handlers, inline models (`RecentFileItem`/`RecentFilesResponse`) move with endpoint | Phase 2, 3 |
 | `nomarr/interfaces/api/web/ml_if.py` | UPDATE — receive work-status + recent-activity handlers | Phase 2 |
 | `nomarr/interfaces/api/web/worker_if.py` | UPDATE — remove restart handler, inline `RestartResponse` moves with endpoint | Phase 2 |
 | `nomarr/interfaces/api/web/admin_if.py` | CREATE **(new)** — restart endpoint + new web admin router | Phase 2 |
 | `nomarr/interfaces/api/web/router.py` | UPDATE — register new admin router | Phase 2 |

### Interfaces Layer — Response Types

 | File | Change Type | Group |
 | --- | --- | --- |
 | `nomarr/interfaces/api/types/admin_types.py` | AUDIT — `WorkerOperationResponse` becomes dead code after v1 deletion | Phase 1 |
 | `nomarr/interfaces/api/types/library_types.py` | UPDATE — `ListLibrariesResponse` gains `aggregate_stats`; `LibraryStatsResponse` becomes dead code | Phase 3 |
 | `nomarr/interfaces/api/types/__init__.py` | AUDIT — barrel re-exports for deleted/dead types | Phase 1, 3 |

### Services Layer

 | File | Change Type | Group |
 | --- | --- | --- |
 | `nomarr/services/infrastructure/worker_system_svc.py` | AUDIT — `pause`/`resume` callers gone after v1 deletion | Phase 1 |
 | `nomarr/services/domain/calibration_svc.py` | UPDATE — consolidate status+progress methods for merged endpoints | Phase 3 |
 | `nomarr/services/domain/tagging_svc.py` | AUDIT — apply-calibration endpoint consolidation may touch this | Phase 3 |
 | `nomarr/services/domain/library_svc/query.py` | UPDATE — pass `library_id` through to file search component | Phase 3 |
 | `nomarr/services/domain/library_svc/admin.py` | UPDATE — `list_libraries()` must also compute aggregate stats for merged response | Phase 3 |

### Components / Persistence Layer

 | File | Change Type | Group |
 | --- | --- | --- |
 | `nomarr/helpers/dto/library_dto.py` | UPDATE — `SearchFilesQuery` gains `library_id` field; DTO additions for aggregate stats | Phase 3 |
 | `nomarr/components/library/search_files_comp.py` | UPDATE — thread `library_id` filter through to AQL query | Phase 3 |
 | `nomarr/persistence/database/library_files_aql/queries.py` | UPDATE — `search_library_files_with_tags` adds AQL filter for `library_id` | Phase 3 |

### Frontend — Shared API Layer

 | File | Change Type | Group |
 | --- | --- | --- |
 | `frontend/src/shared/api/calibration.ts` | UPDATE — remove `getConvergence()`, merge status/progress calls, update URLs and response types | Phase 1, 2, 3 |
 | `frontend/src/shared/api/processing.ts` | UPDATE — work-status URL change | Phase 2 |
 | `frontend/src/shared/api/library.ts` | UPDATE — remove `getLibraryStats()`, recent-activity URL change | Phase 2, 3 |
 | `frontend/src/shared/api/worker.ts` | UPDATE — restart URL change | Phase 2 |
 | `frontend/src/shared/api/files.ts` | UPDATE — add optional `library_id` param to search | Phase 3 |
 | `frontend/src/shared/api/index.ts` | AUDIT — re-exports `getStats`, needs updating after stats merge | Phase 3 |

### Frontend — Feature-Level Consumers

**Stats merge consumers:**

 | File | Change Type |
 | --- | --- |
 | `frontend/src/features/dashboard/DashboardPage.tsx` | UPDATE — consume stats from list response instead of separate call |
 | `frontend/src/features/library/hooks/useLibraryStats.ts` | UPDATE or DELETE — hook may be unnecessary if stats come from list |
 | `frontend/src/features/library/LibraryPage.tsx` | UPDATE — adapt to new stats source |
 | `frontend/src/features/library/components/LibraryStats.tsx` | UPDATE — adapt to new stats shape |

**File search scoping consumers:**

 | File | Change Type |
 | --- | --- |
 | `frontend/src/features/browse/hooks/useLibrarySearch.ts` | UPDATE — thread `library_id` through search calls |
 | `frontend/src/features/browse/BrowseFilesPage.tsx` | UPDATE — pass library context to search |
 | `frontend/src/features/browse/components/SimilarTracks.tsx` | AUDIT — may benefit from library-scoped search |
 | `frontend/src/shared/components/TrackSearchPicker.tsx` | AUDIT — may need `library_id` passthrough |
 | `frontend/src/features/playlist-import/TrackSearchDialog.tsx` | AUDIT — may need `library_id` passthrough |

**Calibration consumers:**

 | File | Change Type |
 | --- | --- |
 | `frontend/src/features/calibration/hooks/` | UPDATE — adapt to merged status endpoints and renamed action URLs |

> **Note on convergence deletion risk:** `getConvergenceStatus()` exists in `frontend/src/shared/api/calibration.ts` but no feature-level UI component or hook actually consumes it — deletion is lower-risk than initially implied.

---

## Proposed Endpoint Surface (After Changes)

### Deleted Endpoints

 | Endpoint | Reason |
 | --- | --- |
 | `POST /api/v1/admin/worker/pause` | No consumers, internal operation |
 | `POST /api/v1/admin/worker/resume` | No consumers, internal operation |
 | `POST /api/v1/admin/calibration/run` | Redundant with async web equivalent |
 | `GET /api/web/calibration/convergence` | Deprecated, frontend caller removed |
 | `GET /api/web/calibration/histogram-status` | Merged into generate/status |
 | `GET /api/web/calibration/histogram-progress` | Merged into generate/status |
 | `GET /api/web/calibration/apply-status` | Merged into apply/status |
 | `GET /api/web/calibration/apply-progress` | Merged into apply/status |
 | `GET /api/web/libraries/stats` | Merged into library list response |

### Moved Endpoints

 | Old Path | New Path | New Router |
 | --- | --- | --- |
 | `GET /api/web/work-status` | `GET /api/web/ml/work-status` | ml_if.py |
 | `GET /api/web/libraries/recent-activity` | `GET /api/web/ml/recent-activity` | ml_if.py |
 | `POST /api/web/worker/restart` | `POST /api/web/admin/restart` | admin_if.py (new) |

### Renamed/Restructured Endpoints

 | Old Path | New Path | Change |
 | --- | --- | --- |
 | `POST /api/web/calibration/start-histogram` | `POST /api/web/calibration/generate` | Clearer verb |
 | `POST /api/web/calibration/start-apply` | `POST /api/web/calibration/apply` | Clearer verb |
 | (new) | `GET /api/web/calibration/generate/status` | Merged status+progress |
 | (new) | `GET /api/web/calibration/apply/status` | Merged status+progress |

### Modified Endpoints

 | Endpoint | Change |
 | --- | --- |
 | `GET /api/web/libraries` | Response now includes `aggregate_stats` field |
 | `GET /api/web/libraries/files/search` | Add optional `library_id` query parameter |

### Unchanged Endpoint Groups

- All analytics endpoints (6) — already well-structured
- Calibration: `DELETE /`, `GET /status`, `GET /history`, `GET /history/{key}`, `GET /histogram/{model}/{head}/{label}`, `GET /histogram`
- All other library CRUD, scan, reconcile, tag, vector endpoints
- All ML model endpoints (5)
- All other web routers (auth, config, fs, metadata, navidrome, playlist-import, processing, tag-curation, tags, vectors)

---

## New Router: admin_if.py (Web)

```
nomarr/interfaces/api/web/admin_if.py
  router = APIRouter(prefix="/admin", tags=["Admin"])
  POST /restart — moves from worker_if.py
```

Register in `router.py` with `router.include_router(admin.router)`.

---

## REST Naming Convention (Proposed ADR)

Based on existing patterns and this cleanup:

1. **Kebab-case** for all URL path segments (already established: `tag-frequencies`, `mood-distribution`, `start-apply`)
2. **Plural nouns** for resource collections (`/libraries`, `/calibrations` would be ideal but `/calibration` is established — keep singular for non-collection resources)
3. **Verb paths** for actions on resources: `POST /calibration/generate`, `POST /calibration/apply`, `POST /{library_id}/scan/quick`
4. **Path params** for resource identity: `/{library_id}`, `/{calibration_key}`
5. **Query params** for optional filtering: `?library_id=`, `?limit=`, `?top_n=`
6. **Nested status** under action paths: `GET /calibration/generate/status` (status of the generate action)
7. **No redundant prefixes** — route function names need not mirror URL paths

---

## Frontend Impact Summary

 | Change | Frontend Files to Update |
 | --- | --- |
 | Delete v1 endpoints | None (no frontend callers) |
 | Delete convergence | `frontend/src/shared/api/calibration.ts` — remove `getConvergence()`, update types |
 | Move work-status | `frontend/src/shared/api/processing.ts` — update URL |
 | Move recent-activity | `frontend/src/shared/api/library.ts` — update URL |
 | Move restart | `frontend/src/shared/api/worker.ts` — update URL |
 | Merge library stats | `frontend/src/shared/api/library.ts` — remove `getLibraryStats()`, extract from list response |
 | Merge calibration status/progress | `frontend/src/shared/api/calibration.ts` — merge polling calls, update response types |
 | Rename calibration actions | `frontend/src/shared/api/calibration.ts` — update URLs |
 | Add library_id to file search | `frontend/src/shared/api/files.ts` — add optional param |
 | Calibration hooks | `frontend/src/features/calibration/hooks/` — update to use merged status endpoints |

---

## Migration Notes

- **No database changes.** All changes are route-level (URL paths, response shapes, router files).
- **No migration files needed.**
- **Alpha software** — breaking changes are acceptable. No backwards-compatible aliases required.

---

## Test Coverage

> **There are essentially NO existing executable endpoint tests to update.** Regression test coverage should be **added**, not updated.

- New endpoint tests should cover: moved endpoints respond at new paths, deleted endpoints return 404/405, consolidated endpoints return merged response shapes, `library_id` filter works in file search.
- E2E test docs at `e2e/TEST_PLAN.md` and `e2e/IMPLEMENTATION_SUMMARY.md` reference old endpoint paths and need docs cleanup to reflect the new surface.
- Calibration hook tests (if any) need updating for merged status responses.

---

## Design Goals

1. Remove dead and redundant endpoints to reduce API surface area
2. Group endpoints by domain responsibility (ML endpoints under /ml, admin under /admin)
3. Consolidate overlapping status/progress endpoint pairs in calibration
4. Establish and codify REST naming conventions as a project ADR
5. Enable library-scoped file search without breaking cross-library search

---

## Constraints

- Alpha software: breaking changes are allowed, no backward-compatible aliases needed
- Web frontend MUST ONLY call `/api/web/*` endpoints (session auth)
- v1 endpoints use API-key auth — different consumer boundary
- Interface layer must call services only (no persistence, no workflows)
- ADR-006: FastAPI routes with `from __future__ import annotations` must import Depends types at runtime
- ADR-013: Tag endpoints go through TaggingService

---

## Open Questions

1. **Worker router after restart move** — Should `worker_if.py` be deleted entirely (it only has the restart endpoint), or kept as a namespace for future worker-specific endpoints?
2. **Calibration singular vs plural** — The router uses `/calibration` (singular). Should it stay singular since it's a process/configuration rather than a collection of resources?
3. **Processing router overlap** — `processing_if.py` has `GET /processing/status`. How does this relate to `GET /ml/work-status` after the move? Are these the same concept or different?
4. **Tag co-occurrence POST** — This is the only analytics endpoint using POST (because it takes a request body). Should it be converted to GET with query params, or is POST acceptable for complex filter requests?
5. **File search endpoint ownership** — After adding `library_id` as an optional parameter, should file search stay under `/libraries/files/search` or move to a dedicated `/files/search` path since it's cross-library by default?

---

## Implementation Phases

### Phase 1: Pure Deletions (No Frontend Impact)

**Scope:** Remove dead v1 endpoints, deprecated convergence, and associated dead code.

 | Step | File | Change |
 | --- | --- | --- |
 | 1a | `nomarr/interfaces/api/v1/admin_if.py` | Delete `admin_pause_worker`, `admin_resume_worker`, `admin_run_calibration` |
 | 1b | `nomarr/interfaces/api/api_app.py` | Remove v1 admin router mount (the v1 admin router will be empty/deleted) |
 | 1c | `nomarr/interfaces/api/web/calibration_if.py` | Delete `get_convergence_status` |
 | 1d | `frontend/src/shared/api/calibration.ts` | Remove `getConvergence()` function and types |
 | 1e | Remove any frontend components referencing convergence | Search and remove (note: no feature-level consumers currently exist — low risk) |
 | 1f | `nomarr/interfaces/api/types/admin_types.py` | Audit — `WorkerOperationResponse` becomes dead code, remove if unused |
 | 1g | `nomarr/interfaces/api/types/__init__.py` | Remove barrel re-exports for deleted types |

If `admin_if.py` is empty after deletions, delete the file and remove its router registration from `api_app.py`.

**Risk:** Low. No known consumers for v1 endpoints. Convergence is deprecated. `getConvergenceStatus()` has no feature-level UI consumer.

### Phase 2: Moves and Renames (Frontend URL Updates)

**Scope:** Relocate endpoints to correct routers. Frontend changes are URL-only.

 | Step | Change | Backend | Frontend |
 | --- | --- | --- | --- |
 | 2a | Move work-status to ML | Move handler from `info_if.py` to `ml_if.py` | Update URL in `processing.ts` |
 | 2b | Move recent-activity to ML | Move handler + inline models (`RecentFileItem`/`RecentFilesResponse`) from `library_if.py` to `ml_if.py` | Update URL in `library.ts` |
 | 2c | Move restart to admin | Create `admin_if.py`, move handler + inline `RestartResponse` from `worker_if.py` | Update URL in `worker.ts` |
 | 2d | Rename calibration actions | `start-histogram` → `generate`, `start-apply` → `apply` in `calibration_if.py`; update `calibration_svc.py` if method names reference old route names | Update URLs in `calibration.ts` |

**Risk:** Medium. Frontend must be updated in lockstep with backend.

### Phase 3: Consolidations (Response Type Changes)

**Scope:** Merge endpoints and modify response shapes. Requires frontend logic changes and backend pipeline updates.

 | Step | Change | Backend | Frontend |
 | --- | --- | --- | --- |
 | 3a | Merge calibration status+progress | Combine response types in `calibration_svc.py`, create merged endpoints in `calibration_if.py`, delete old ones | Update calibration hooks to use merged endpoints, update response type handling |
 | 3b | Merge library stats into list | `library_svc/admin.py`: `list_libraries()` computes aggregate stats; `library_dto.py`: DTO additions; `library_types.py`: `ListLibrariesResponse` gains `aggregate_stats`; delete `/stats` endpoint from `library_if.py` | Remove `getLibraryStats()` from `library.ts`; update `index.ts` re-exports; update `DashboardPage.tsx`, `useLibraryStats.ts`, `LibraryPage.tsx`, `LibraryStats.tsx` to consume stats from list response |
 | 3c | Add library_id to file search | Full pipeline: `library_dto.py` (`SearchFilesQuery` + `library_id`), `library_svc/query.py` (pass-through), `search_files_comp.py` (component filter), `library_files_aql/queries.py` (`search_library_files_with_tags` AQL filter), `library_if.py` (route param) | Add optional `library_id` to `files.ts`; thread through `useLibrarySearch.ts`, `BrowseFilesPage.tsx`; audit `SimilarTracks.tsx`, `TrackSearchPicker.tsx`, `TrackSearchDialog.tsx` |

**Risk:** Higher. Response shape changes require careful frontend adaptation. File search `library_id` touches 4 backend layers (interface → service → component → persistence).

### Phase 4: Convention ADR

**Scope:** Document REST naming conventions based on established patterns + this cleanup.

 | Step | Action |
 | --- | --- |
 | 4a | Draft ADR for REST naming conventions (kebab-case, plural resources, verb paths, etc.) |
 | 4b | Audit remaining endpoints against convention, note any non-conforming paths for future cleanup |

---

## Appendix: Research Findings

### Codebase Patterns Discovered

1. **Kebab-case already standard** — All existing routes use kebab-case (`tag-frequencies`, `mood-distribution`, `start-histogram`, `start-apply`, `recent-activity`). No snake_case or camelCase routes found.

2. **Action pattern established** — `POST /{library_id}/scan/quick`, `POST /{library_id}/scan/full`, `POST /{library_id}/reconcile` — library-scoped actions use `POST /{id}/verb` pattern.

3. **Background task pattern** — Calibration uses `POST /start-X` to trigger, `GET /X-status` to poll. This cleanup normalizes to `POST /X` to trigger, `GET /X/status` to poll.

4. **Info router is a catch-all** — `info_if.py` uses empty prefix, making its routes appear at `/api/web/` root level. This is why work-status is at `/api/web/work-status` not `/api/web/info/work-status`.

5. **Library router is overloaded** — 23 endpoints covering CRUD, scanning, reconciliation, tag operations, vector config, file search, stats, and recent activity. This design moves 2 endpoints out (recent-activity, stats merge).

6. **Frontend API layer is well-organized** — Each backend router has a corresponding `frontend/src/shared/api/*.ts` file. Changes are mechanical: update URLs and types in the matching file.

7. **Two LibraryStatsResponse types exist** — One in `analytics_types.py` (file_count, total_duration_ms, total_file_size_bytes, avg_track_length_ms) and one in `library_types.py` (total_files, unique_artists, unique_albums, total_duration_seconds). The library_types version is the one used by the `/libraries/stats` endpoint. The analytics one is used internally by analytics.
