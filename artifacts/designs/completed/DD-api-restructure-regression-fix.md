# Post-API-Restructure Regression Fix — Design Document

**Status:** Completed  
**Author:** rnd-dd-author  
**Created:** 2026-04-06  

**Related Documents:**

- [](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) —
- [](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) —
- [](artifacts/decisions/ADR-020-rest-api-naming-convention-kebab-case-full-words.md) —
- [](support-debugger#L2,L3,L4,L5,L6,L7) —
- [](rnd-manager#L27,L28) —

---

## Scope

nomarr/persistence/database, nomarr/components/library, nomarr/workflows/library, nomarr/interfaces/api

---

## Problem Statement

The API restructure (commit d9798dc, ~230 files, ADR-020) combined with the V021 schema migration (ADR-004) introduced 9 regressions across the backend. Two are production crashes (P0), four are silent failures returning empty/incorrect data (P1), two are scan-state reader inconsistencies (part of BREAK-5), and one is dead code (P2).

**P0 crashes** affect `/machine-learning/recent-activity` (Pydantic field mismatch: AQL returns `scanned_at`, model requires `last_tagged_at`) and `/library/file/search` (V021 nulled `library_id` on all library_files documents; AQL returns `library_id: null`, downstream `encode_id(None)` raises `TypeError`).

**P1 silent failures** affect `get_files_with_incomplete_tags()` (AQL `FILTER file.library_id == @library_id` never matches because library_id is null), `get_all_tracks()` (same null library_id filter), and scan state tracking (the `library_has_scan` edge is never created for libraries added after V021, causing all scan status queries to return "idle" regardless of actual scan activity).

**P2 dead code**: `admin_types.py` and `calibration_types.py` are exported from `nomarr/interfaces/api/types/__init__.py` but imported by no active router.

The scan state break (BREAK-5) requires an architectural decision about how scan progress tracking aligns with ADR-003's pure boolean state graph pattern.

---

## Architecture

## Breaks Inventory

### P0 — Production Crashes

#### BREAK-1: `/machine-learning/recent-activity` 500

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | AQL `get_recently_processed` (queries.py:486–547) projects `scanned_at: file.scanned_at` in both RETURN blocks. `RecentFileItem` (ml_if.py:27–35) requires field `last_tagged_at: int` with no default. Pydantic `ValidationError` on every response. |
 | **Error chain** | AQL returns `{..., scanned_at: 1712345678}` → `RecentFileItem(**doc)` → missing `last_tagged_at` → ValidationError → caught by except-all → HTTP 500 |
 | **Impact** | Recent activity panel completely broken for all users. |
 | **Fix** | Rename AQL projection alias in both RETURN blocks: `scanned_at: file.scanned_at` → `last_tagged_at: file.scanned_at`. Update docstring `Returns:` section. Two one-word changes. |
 | **Files** | `nomarr/persistence/database/library_files_aql/queries.py` (lines ~522, ~540) |
 | **Complexity** | TRIVIAL |

#### BREAK-2: `/library/file/search` 500

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | V021 migration set `library_id: null` on all library_files documents (moved relationship to `library_contains_file` edge). `search_library_files_with_tags` AQL still does `RETURN MERGE(file, { tags: tags })` which includes `library_id: null`. Downstream: `_library_mapping.py:30` passes `None` → `library_types.py` calls `encode_id(None)` → `TypeError: argument of type 'NoneType' is not iterable`. |
 | **Error chain** | V021 nulls `library_id` → AQL returns `library_id: null` → mapping passes `None` to `encode_id()` → `TypeError` → HTTP 500 "Failed to search files" |
 | **Impact** | File search completely broken for all users. |
 | **Fix** | Add INBOUND edge lookup in AQL RETURN block: `LET lib_id = FIRST(FOR lib IN INBOUND file._id library_contains_file LIMIT 1 RETURN lib._id)`, then `RETURN MERGE(file, { tags: tags, library_id: lib_id })`. The `library_id: lib_id` in MERGE's second arg overrides the null from the file doc. |
 | **Files** | `nomarr/persistence/database/library_files_aql/queries.py` (search query RETURN block, ~line 462–479) |
 | **Complexity** | SMALL |

---

### P1 — Incorrect Behavior (Silent Failures)

#### BREAK-3: `get_files_with_incomplete_tags()` returns empty results

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `file_states_aql.py:902` has `FILTER file.library_id == @library_id` — but `library_id` is null on all library_files docs after V021. Filter never matches when `library_id` is provided. |
 | **Also** | Line ~933 returns `library_id: file.library_id` in results (always null). |
 | **Impact** | Any feature depending on "files with incomplete tags" in a specific library gets nothing. Affects calibration and tag writing workflows silently. |
 | **Fix** | Replace `FILTER file.library_id == @library_id` with edge-based library scoping. Change the query to start from `FOR file IN INBOUND @library_id library_contains_file` (filtering tagged files via the existing `file_has_state` subquery), then derive `library_id` from the bind var in the RETURN block. |
 | **Files** | `nomarr/persistence/database/file_states_aql.py` (~lines 890–940) |
 | **Complexity** | SMALL |

#### BREAK-4: `get_all_tracks()` returns empty when library_id provided

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `tracks.py:105` has `FILTER f.library_id == @library_id` — same null `library_id` issue as BREAK-3. |
 | **Impact** | Navidrome integration and any track listing by library silently returns nothing. |
 | **Fix** | Same edge-traversal pattern. When `library_id` is provided, start with `FOR f IN OUTBOUND @library_id library_contains_file` instead of `FOR f IN library_files` with filter. When not provided, keep the current `FOR f IN library_files` scan. |
 | **Files** | `nomarr/persistence/database/library_files_aql/tracks.py` (~line 101–107) |
 | **Complexity** | SMALL |

#### BREAK-4b: `validate_unchanged_files()` returns empty when library_id provided

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `validate_scan_state_comp.py:87` has `FILTER file.library_id == @library_id` — same V021 null `library_id` pattern as BREAK-3/4. |
 | **Called from** | `scan_library_full_wf.py:315` during full library scans. |
 | **Impact** | Unchanged-file healing for short files silently stops matching during full scans. Files that haven't changed are not recognized as unchanged, defeating the optimization that skips re-processing. |
 | **Fix** | Same edge-traversal pattern: replace `FILTER file.library_id == @library_id` with `FOR file IN INBOUND @library_id library_contains_file` scoping. |
 | **Files** | `nomarr/components/library/validate_scan_state_comp.py` (~line 87) |
 | **Complexity** | SMALL |

#### BREAK-5: Scan state tracking broken

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `library_has_scan` edge is never created for libraries added after V021. Multiple contributing factors: (1) `library_admin_comp.create_library` doesn't initialize scan doc/edge; (2) `library_scans_aql.update_scan` UPSERTs scan doc but never creates edge; (3) `get_or_create_scan()` correctly creates both but is never called in production; (4) `list_libraries` AQL does `OUTBOUND lib library_has_scan` → no edge → scan=null → fallback "idle". |
 | **Error chain** | `create_library` → no scan init → first scan → `update_scan_progress` → `libraries.update_scan_status` → `library_scans.update_scan` → UPSERT doc only (no edge) → `list_libraries` traverses missing edge → scan=null → "idle" always |
 | **Impact** | `is_scanning=false`, `progress=0`, `status=idle`, `total=0` during active scans. Frontend never polls. Buttons re-enable immediately after scan start. |
 | **Files** | `nomarr/persistence/database/library_scans_aql.py`, `nomarr/persistence/database/libraries_aql.py`, `nomarr/components/library/library_admin_comp.py`, `nomarr/components/library/work_status_comp.py`, `nomarr/workflows/library/scan_setup_wf.py`, `nomarr/services/infrastructure/file_watcher_svc.py` |
 | **Complexity** | MEDIUM (requires architectural decision) |
 | **Additional readers** | Two additional scan_status readers must be migrated as part of this fix (see BREAK-5a and BREAK-5b below). |

#### BREAK-5a: `file_watcher_svc` startup recovery reads scan_status instead of pipeline_state

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `file_watcher_svc.py:207–215` startup recovery iterates `list_libraries()`, checks `lib.get("scan_status") == "scanning"`, and calls `update_scan_status(status="idle")`. This reads scan state from the scan document, not from pipeline_state. |
 | **Overlap** | `pipeline_svc.py:60–71` already recovers stale `PIPELINE_SCANNING` via pipeline state. These two recovery paths may be redundant. |
 | **Impact** | If scan_status diverges from pipeline_state (which it does when the edge is missing), startup recovery either resets a scan that pipeline_svc would also reset, or misses a scan that only pipeline_state knows about. |
 | **Fix** | Either: (a) migrate to read from `pipeline_state` instead of `scan_status`, OR (b) remove the recovery block entirely if `pipeline_svc` already covers the same case. Document whichever approach is chosen. |
 | **Files** | `nomarr/services/infrastructure/file_watcher_svc.py` (~lines 207–215) |
 | **Complexity** | SMALL |

#### BREAK-5b: `_is_scan_running()` reads scan_status

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `library_admin_comp.py:168` — `_is_scan_running()` checks `any(lib.get("scan_status") == "scanning" ...)`. Called from `clear_library_data()` at line 140. |
 | **Impact** | If pipeline_state becomes the source of truth for "is scanning" (per our dual-purpose split), this helper returns stale results. |
 | **Fix** | Migrate `_is_scan_running()` to check pipeline_state instead of scan_status. |
 | **Files** | `nomarr/components/library/library_admin_comp.py` (~line 168) |
 | **Complexity** | SMALL |

---

### P2 — Dead Code

#### BREAK-6: Orphaned type models

 | Attribute | Detail |
 | ----------- | -------- |
 | **Root cause** | `admin_types.py` and `calibration_types.py` are exported in `nomarr/interfaces/api/types/__init__.py` but not imported by any active router after the restructure. |
 | **Fix** | Remove from `__init__.py` exports. Optionally delete the files. |
 | **Impact** | No runtime impact — dead code only. |
 | **Files** | `nomarr/interfaces/api/types/__init__.py`, `nomarr/interfaces/api/types/admin_types.py`, `nomarr/interfaces/api/types/calibration_types.py` |
 | **Complexity** | TRIVIAL |

---

## Scan State Architecture Decision (BREAK-5)

### Current Architecture

Two separate mechanisms track scan-related state:

1. **`library_has_pipeline_state`** → ADR-003-style boolean state graph. Edge from library to state vertex (`library_pipeline_states/scanning`, `library_pipeline_states/idle`, etc.). Answers: "What workflow phase is this library in?"
2. **`library_has_scan`** → Edge to `library_scans` document containing `{status, files_processed, files_total, scan_type, error, started_at, completed_at}`. Answers: "What is the scan progress?"

The problem: `compute_work_status` reads `scan_status` from the `library_has_scan` traversal to determine `is_scanning`. But the edge is never created, so it always reads "idle". Meanwhile, `library_has_pipeline_state` correctly has `PIPELINE_SCANNING` when a scan is active — but nothing reads it for the `is_scanning` determination.

### ADR-003 Alignment Constraint

The user has rejected the `library_has_scan` edge/document approach for tracking scan STATE. ADR-003 states: "Zero payload on edges — all domain data lives on documents or in separate collections." The pipeline state graph already handles the "is this library scanning?" question correctly via `PIPELINE_SCANNING`.

### Recommended Approach: Dual-Purpose Split

**State determination** (is it scanning?) → Read from `library_has_pipeline_state`. This is the ADR-003-compliant answer.

**Progress data** (files_processed, files_total, scan_type, error) → Keep in `library_scans` collection as operational metadata, NOT as a state indicator. Fix the edge creation so the progress data is accessible.

Concrete changes:

1. **`compute_work_status`**: Derive `is_scanning` from `pipeline_states` dict (already passed as parameter). A library is scanning when `pipeline_states.get(lib_id) == "scanning"`. Stop reading `scan_status` from the library/scan traversal for this purpose.

2. **`list_libraries` AQL**: The `library_has_scan` traversal stays for returning progress data to the frontend. Fix the edge creation so it actually works.

3. **`library_scans_aql.update_scan`**: After UPSERT into `library_scans`, also UPSERT the `library_has_scan` edge. The method already receives `library_id`.

4. **`library_admin_comp.create_library`**: Call `db.library_scans.get_or_create_scan(library_id)` after creating the library to initialize scan doc + edge.

5. **`scan_setup_wf`**: The `scan_status == "scanning"` guard check should read from pipeline state, not scan document status.

This approach keeps ADR-003's pure boolean state graph for state determination while using the scan document purely for progress metadata. The `library_has_scan` edge becomes a structural relationship ("this library has scan progress tracking"), not a state indicator.

---

## Implementation Phases

### Phase 1: P0 Fixes (Production Crash Relief)

**Goal**: Restore `/machine-learning/recent-activity` and `/library/file/search` to working state.

 | Step | File | Change |
 | ------ | ------ | -------- |
 | 1a | `queries.py` ~line 522 | Rename `scanned_at:` → `last_tagged_at:` in first RETURN block |
 | 1b | `queries.py` ~line 540 | Same rename in second RETURN block |
 | 1c | `queries.py` ~line 490 | Update docstring Returns section |
 | 1d | `queries.py` ~line 462-479 | Add `LET lib_id = FIRST(FOR lib IN INBOUND file._id library_contains_file LIMIT 1 RETURN lib._id)` and update RETURN to include `library_id: lib_id` |

**Verification**: `GET /api/web/machine-learning/recent-activity?limit=5` returns 200 with `last_tagged_at` field. `GET /api/web/library/file/search?q=test` returns 200 with non-null `library_id` values.

### Phase 2: P1 Silent Failures (library_id Filters)

**Goal**: Fix all AQL queries that filter on `file.library_id` (now null after V021).

 | Step | File | Change |
 | ------ | ------ | -------- |
 | 2a | `file_states_aql.py` ~line 897-905 | Replace `FILTER file.library_id == @library_id` with edge-based scoping: start from `FOR file IN INBOUND @library_id library_contains_file` |
 | 2b | `file_states_aql.py` ~line 933 | Fix RETURN to derive `library_id` from `@library_id` bind var |
 | 2c | `tracks.py` ~line 101-107 | When `library_id` provided, use `FOR f IN OUTBOUND @library_id library_contains_file` instead of filter on null field |
 | 2d | `validate_scan_state_comp.py` ~line 87 | Replace `FILTER file.library_id == @library_id` with edge-based scoping (same pattern as 2a) |

**Verification**: `get_files_with_incomplete_tags(library_id="libraries/X")` returns non-empty list for a library with tagged files. `get_all_tracks(library_id="libraries/X")` returns tracks. `validate_unchanged_files()` correctly identifies unchanged files during full scan.

### Phase 3: Scan State Architecture Fix

**Goal**: Fix scan state tracking per the dual-purpose split architecture above.

 | Step | File | Change |
 | ------ | ------ | -------- |
 | 3a | `library_scans_aql.py:update_scan` | Add UPSERT for `library_has_scan` edge after scan doc UPSERT |
 | 3b | `library_admin_comp.py:create_library` | Call `db.library_scans.get_or_create_scan(library_id)` after library creation |
 | 3c | `work_status_comp.py:compute_work_status` | Derive `is_scanning` from `pipeline_states` param instead of `scan_status` field |
 | 3d | `scan_setup_wf.py` | Change `scan_status == "scanning"` guard to check pipeline state |
 | 3e | `libraries_aql.py` | Verify `list_libraries` and `get_library` AQL handle missing scan edge gracefully (already has fallback) |
 | 3f | `file_watcher_svc.py` ~lines 207-215 | Migrate startup recovery to read pipeline_state instead of scan_status, OR remove if redundant with `pipeline_svc.py:60-71` recovery. Requires investigation during implementation. |
 | 3g | `library_admin_comp.py:_is_scan_running` ~line 168 | Migrate `_is_scan_running()` to check pipeline_state instead of `scan_status` |

**Verification**: Create new library → scan it → `GET /api/web/library` shows `scanStatus: "scanning"` and progress updates. `GET /api/web/machine-learning/work-status` shows `is_scanning: true` during scan. Frontend polls and disables buttons.

### Phase 4: P2 Cleanup

**Goal**: Remove dead code.

 | Step | File | Change |
 | ------ | ------ | -------- |
 | 4a | `nomarr/interfaces/api/types/__init__.py` | Remove `admin_types` and `calibration_types` imports/exports |
 | 4b | `admin_types.py`, `calibration_types.py` | Delete files (or keep as tombstones with deprecation comment) |

**Verification**: `python -c "from nomarr.interfaces.api.types import *"` succeeds without importing dead modules. Lint passes.

---

## Design Goals

1. Restore all P0 endpoints to working state immediately
2. Fix all AQL queries broken by V021's library_id nullification
3. Align scan state tracking with ADR-003's pure boolean state graph for state determination
4. Remove dead code left by the API restructure
5. Zero new migrations required (all fixes are code-level corrections to match the V021 schema)

---

## Constraints

- **ADR-003**: Pure boolean state graph. State determined by edge existence to state vertex, not by payload fields. `is_scanning` must derive from `library_has_pipeline_state`, not from `library_scans.status`.
- **ADR-004**: Schema refactor — `library_id` moved to edges. All queries filtering on `file.library_id` must use `library_contains_file` edge traversal instead.
- **ADR-012**: Server-side pagination must preserve real totals. Count queries in BREAK-2 fix must not break pagination.
- **ADR-020**: Kebab-case full words naming. No endpoint renames needed (already done in restructure).
- **No new migrations**: All breaks are code-level. The V021 schema is correct; the AQL queries and components didn't update to match.
- **Forward-only**: Alpha policy. No rollback path needed.

---

## Open Questions

1. **BREAK-5 edge creation in `update_scan`**: Should the UPSERT edge be in the same AQL query as the scan doc UPSERT (single round-trip) or a separate query? Single query is more efficient but more complex AQL.
2. **Healing migration for existing libraries**: Libraries created between V021 and this fix have no `library_has_scan` edge. Should we add a lightweight healing migration, or rely on `get_or_create_scan` being called on next scan start?
3. **Dead type files (BREAK-6)**: Delete entirely or keep as empty tombstones? Deleting is cleaner; keeping avoids breaking any hypothetical external imports.

---

## Files Changed (Complete Manifest)

 | File | Phases | Changes |
 | ------ | -------- | --------- |
 | `nomarr/persistence/database/library_files_aql/queries.py` | 1 | BREAK-1: Rename `scanned_at` → `last_tagged_at` alias (×2). BREAK-2: Add INBOUND edge lookup for `library_id` in search RETURN. |
 | `nomarr/persistence/database/file_states_aql.py` | 2 | BREAK-3: Replace `FILTER file.library_id` with edge-based scoping; fix RETURN `library_id`. |
 | `nomarr/persistence/database/library_files_aql/tracks.py` | 2 | BREAK-4: Replace `FILTER f.library_id` with edge traversal when `library_id` provided. |
 | `nomarr/persistence/database/library_scans_aql.py` | 3 | BREAK-5: Add `library_has_scan` edge UPSERT to `update_scan`. |
 | `nomarr/persistence/database/libraries_aql.py` | 3 | BREAK-5: Verify graceful fallback in `list_libraries`/`get_library` AQL (likely no change). |
 | `nomarr/components/library/library_admin_comp.py` | 3 | BREAK-5: Call `get_or_create_scan` after library creation. BREAK-5b: Migrate `_is_scan_running()` to check pipeline_state. |
 | `nomarr/components/library/work_status_comp.py` | 3 | BREAK-5: Derive `is_scanning` from `pipeline_states`, not `scan_status`. |
 | `nomarr/workflows/library/scan_setup_wf.py` | 3 | BREAK-5: Guard check reads pipeline state instead of `scan_status`. |
 | `nomarr/components/library/validate_scan_state_comp.py` | 2 | BREAK-4b: Replace `FILTER file.library_id == @library_id` with edge-based scoping. |
 | `nomarr/services/infrastructure/file_watcher_svc.py` | 3 | BREAK-5a: Migrate startup recovery scan_status reader to pipeline_state, or remove if redundant with pipeline_svc recovery. |
 | `nomarr/interfaces/api/types/__init__.py` | 4 | BREAK-6: Remove dead `admin_types`/`calibration_types` exports. |
 | `nomarr/interfaces/api/types/admin_types.py` | 4 | BREAK-6: Delete file. |
 | `nomarr/interfaces/api/types/calibration_types.py` | 4 | BREAK-6: Delete file. |

## Migration Requirements

**None.** All 6 breaks are code-level — AQL queries and components that weren't updated to match the V021 schema. The schema itself (edges, collections, indexes) is correct. No new migration needed.

One optional consideration: a lightweight healing query to create `library_has_scan` edges for libraries created between V021 and this fix. This could be a migration or a one-time startup check. See Open Question #2.

## Verification Plan

 | Break | Test | Expected Result |
 | ------- | ------ | ----------------- |
 | BREAK-1 | `GET /api/web/machine-learning/recent-activity?limit=5` | 200, response items have `last_tagged_at` (integer) |
 | BREAK-2 | `GET /api/web/library/file/search?q=test` | 200, all items have non-null `library_id` |
 | BREAK-3 | Call `get_files_with_incomplete_tags(library_id="libraries/{key}")` for a library with tagged files | Non-empty result list with correct `library_id` values |
 | BREAK-4 | Call `get_all_tracks(library_id="libraries/{key}")` for a library with valid files | Non-empty track list |
 | BREAK-4b | Run full scan on library with unchanged files → check `validate_unchanged_files()` output | Non-empty result list of unchanged files |
 | BREAK-5 | Create new library → start scan → `GET /api/web/library` | `scanStatus: "scanning"`, `scanProgress > 0` during scan |
 | BREAK-5 | During scan → `GET /api/web/machine-learning/work-status` | `is_scanning: true`, `scanning_libraries` non-empty |
 | BREAK-6 | `python -c "from nomarr.interfaces.api.types import *"` | No import errors; `admin_types`/`calibration_types` symbols absent |
 | ALL | `python -m pytest tests/ -x` | All tests pass |
 | ALL | Lint passes (`ruff check nomarr/`) | Zero errors |

## Verified Healthy (Not in Scope)

The following areas were spot-checked and found healthy. Not exhaustive audits — representative samples only:

- ML pipeline: Spot-checked 5 critical method calls in `discovery_worker.py` (e.g. `find_ml_complete_libraries`, `update_pipeline_state`); all present and correctly wired
- `find_ml_complete_libraries()` confirmed at `library_pipeline_states_aql.py:364`
- Frontend URLs: Spot-checked 12 representative routes across library, ML, settings, and admin sections; all resolve to valid backend endpoints
- Service method calls: Spot-checked 6 router files (`library_router`, `ml_router`, `settings_router`, `auth_router`, `analytics_router`, `metadata_router`); no broken calls found
- Pipeline state machine (10 states) works correctly
- Vector services, analytics, auth, config, metadata, calibration endpoints: spot-checked representative endpoints, no issues found
- Tag curation and Navidrome endpoints: spot-checked, healthy

## Source Logs

- `support-debugger#L2` — Root cause: recent-activity field mismatch
- `support-debugger#L3` — Root cause: library_has_scan edge never created
- `support-debugger#L4` — Root cause: file/search library_id null after V021
- `support-debugger#L5` — Confirmed: scan edge creation never called in prod
- `support-debugger#L6` — Confirmed: AQL scanned_at vs last_tagged_at
- `support-debugger#L7` — Corrected: TypeError from encode_id(None), not KeyError
- `rnd-manager#L27, #L28` — Dispatch and synthesis of break inventory
