# ML Pipeline End-to-End Automation — Design Document

**Status:** Draft
**Author:** RnD-Manager
**Created:** 2026-04-04
**Revised:** 2026-04-04 — Architecture change: library state graph replaces polling/derived-state approach

**Related Documents:**
- [ADR-003](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — Pure Boolean State Graph for File Processing Pipeline
- [ADR-004](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Schema Refactor V1 — Graph Normalization
- [ADR-008](artifacts/decisions/ADR-008-database-only-tag-writes-no-audio-file-writeback.md) — Two-Phase Tag Curation — Deferred File Writeback

---

## Scope

`services/infrastructure` (pipeline service — startup recovery + calibration trigger wiring), `services/domain` (tagging rename + background refactor), `interfaces/api/web` (endpoint rename + new status endpoint), `helpers/dto` (new DTO + library field additions), `persistence/database` (new `library_pipeline_states` vertex collection, new `library_has_pipeline_state` edge collection, state transition operations), `components/workers` (post-tagging library state check), `components/library` (field forwarding), `frontend/` (API rename + auto-write toggle), `migrations/` (new collections + seed states + derive initial state for existing libraries)

---

## Problem Statement

After a library scan, Nomarr's ML pipeline requires manual API calls to complete: start calibration and write tags to files. This forces users to babysit the system, checking progress and clicking through steps. The desired UX is: add a library → everything happens automatically. The only manual step should optionally be "review before writing tags to files."

**Current Pipeline (6 stages):**

| Stage | Name | Status |
|-------|------|--------|
| 1 | Library Scan | AUTOMATED (background task) |
| 2 | ML Processing | AUTOMATED (workers poll for untagged files) |
| 3 | Vector Promotion | AUTOMATED (workers auto-promote on idle) |
| 4 | Histogram Calibration | MANUAL ❌ |
| 5 | Apply Calibration | SEMI-AUTOMATED (auto after calibration via `post_generation_hook`) |
| 6 | Write Tags to Files | MANUAL ❌ |

Stages 4 and 6 require manual user intervention. Stage 5 fires automatically after stage 4 via `post_generation_hook` but requires stage 4 to be manually triggered first. The goal is to eliminate all manual steps, with an optional gate before file writing controlled by the per-library `library_auto_write` setting.

---

## Architecture

### Design: Library Pipeline State Graph — Event-Driven Transitions

The pipeline is **per-library**. Each library's pipeline progress is tracked via a **stored state edge** in the graph database, mirroring the `file_has_state` pattern from ADR-003. There is no poll loop. All state transitions are event-driven — triggered by completion callbacks from existing services and workers.

### State Collection

New `library_pipeline_states` **vertex collection** with singleton state vertices (seeded once at migration time):

| Key | Meaning |
|-----|---------|
| `library_pipeline_states/idle` | No files in library or pipeline not yet started |
| `library_pipeline_states/ml_running` | Scan complete; ML workers are processing files |
| `library_pipeline_states/ml_complete` | All files in library are tagged; ready for calibration |
| `library_pipeline_states/calibrating` | Calibration histogram generation in progress |
| `library_pipeline_states/applying` | Applying calibration thresholds to tagged files |
| `library_pipeline_states/write_ready` | Apply complete, `library_auto_write=False`; user must trigger write |
| `library_pipeline_states/writing` | Tag write in progress |
| `library_pipeline_states/complete` | All stages done |

### Edge Collection

New `library_has_pipeline_state` **edge collection**: `libraries → library_pipeline_states`

- Exactly **one** edge per library (single-axis, unlike `file_has_state` which has 8 axes)
- No payload on edges — purely structural
- Atomic transition: REMOVE old edge + INSERT new edge (same pattern as `file_has_state` `_transition_state()`)

### State Transitions (Event-Driven)

| Event | Transition | Trigger Location |
|-------|-----------|-----------------|
| Library created | `→ idle` | Library creation workflow |
| Scan completes | `idle → ml_running` | Scan completion callback |
| Worker processes last untagged file in library | `ml_running → ml_complete` → trigger calibration | Worker post-tagging check |
| Calibration generation starts | `ml_complete → calibrating` (all enabled libraries simultaneously) | `LibraryPipelineService` calibration trigger |
| Calibration generation succeeds (`post_generation_hook`) | `calibrating → applying` → trigger apply | Calibration completion callback |
| Apply calibration completes | `applying → writing` (if `auto_write=True` + `write_mode != none`) OR `applying → write_ready` | Apply completion callback |
| Write tags to files completes | `writing → complete` | Write completion callback |
| User manually triggers write (from `write_ready`) | `write_ready → writing` | `POST /{id}/write-tags` endpoint |
| New files added to library in `complete` state | `complete → ml_running` | Scan completion callback |

### ML Completion Detection

Workers have no existing "library done" signal. **Solution:** after a worker calls `set_tagged(file_id)`, it performs a single follow-up AQL query:

```aql
LET lib_id = FIRST(FOR lib IN INBOUND @file_id library_contains_file RETURN lib._id)
LET untagged_count = LENGTH(
    FOR f IN OUTBOUND lib_id library_contains_file
        FOR e IN file_has_state FILTER e._from == f._id AND e._to == 'file_states/not_tagged'
        RETURN 1
)
RETURN { lib_id, untagged_count }
```

If `untagged_count == 0`, the worker transitions the library state from `ml_running → ml_complete` and fires the calibration trigger.

**Library ID derivation:** The worker does not need `library_id` in its payload. The AQL derives `lib_id` via `INBOUND library_contains_file` traversal from the file being processed. This is a single-hop graph traversal — negligible cost given it only fires once per file at tagging completion.

**Idempotency:** If two workers race on the last two files, the second transition from `ml_running → ml_complete` is a no-op (edge already points at `ml_complete`). The calibration trigger checks `is_generation_running()` guard — an existing idempotency mechanism.

### Calibration (Global Scope)

Calibration is global — one trigger applies to all libraries. When a library reaches `ml_complete`:

1. Check `is_generation_running()` — if already running, no-op (existing guard, already idempotent)
2. Bulk transition: all enabled libraries in `ml_complete` → `calibrating`
3. Trigger `start_histogram_calibration_background()`
4. `post_generation_hook` fires on success → bulk transition all `calibrating` → `applying` → trigger `start_apply_calibration_background()`

**New library added to established system (calibration data exists):**
When a new library is added and calibration data already exists (`get_generation_result() is not None`), the new library skips calibration entirely. After ML completes, it goes `ml_complete → applying` directly — existing calibration data is applied without re-running global calibration.

### Elimination of `initial_calibration_done`

The `initial_calibration_done` boolean is **not needed** — it is absorbed into the library state itself:

- If library state is `applying`, `write_ready`, `writing`, or `complete` → initial calibration has occurred
- No separate flag needed — the state graph captures this information structurally
- **No `initial_calibration_done` field on library documents**

### `library_auto_write` Remains

`library_auto_write` is a user-configurable boolean field on the library document. The transition logic uses it at the `applying → write_ready/writing` branch point:
- `library_auto_write=True` AND `file_write_mode != "none"` → `applying → writing` (automatic)
- Otherwise → `applying → write_ready` (manual gate)

### No Poll Loop

**No 30-second poll loop.** No `_tick_lock`, no background thread, no three Regimes. All transitions are event-driven:

1. **Startup recovery scan** — on application start, iterate all enabled libraries, check their stored state vs. actual file counts, and correct any inconsistency (covers crash recovery)
2. **No recurring poll** — all subsequent transitions are triggered by event callbacks

### Error Handling

**No retry logic.** No backoff, no retries, no ERROR_WAIT states. If any step fails, it errors loudly. Failures surface immediately in logs. The startup recovery scan will detect inconsistent states on next application restart and correct them.

### Special Cases

**Empty library (0 files):** State is `idle`. No transitions fire. Correct.

**Library with `file_write_mode: "none"`:** Guard at `applying` transition sends library to `write_ready` instead of `writing`. Setting `library_auto_write=True` on a `none`-mode library is a no-op for automation but remains valid configuration if the user later changes write mode.

**Calibration global scope:** When any library reaches `ml_complete`, calibration benefits all libraries. All enabled libraries in `ml_complete` advance to `calibrating` simultaneously. Libraries still in `ml_running` will hit calibration when their ML completes — if calibration data already exists by then, they skip to `applying` directly.

### Navidrome Rescan Side Effect

The current `POST /{id}/reconcile-tags` endpoint calls `navidrome_service.trigger_rescan()` after writeback completes. Since `write_tags_to_files` now runs as a background task, this side effect must move to the background completion callback within the write workflow. The rescan fires after the background write job completes, not after the endpoint returns.

### Key Components

| Component | Layer | Responsibility |
|-----------|-------|----------------|
| `LibraryPipelineStatesOperations` | `persistence/database` | State transitions (REMOVE + INSERT edge), state queries, bulk transitions |
| `LibraryPipelineService` | `services/infrastructure/pipeline_svc.py` | Startup recovery scan, calibration trigger logic, wiring event callbacks |
| Worker post-tagging check (inline or `WorkerCompletionComp`) | `components/workers` | After `set_tagged()`: query untagged count → if 0, transition `ml_running → ml_complete` → fire calibration trigger |
| `CalibrationService` | `services/domain` | Histogram calibration (existing — unchanged except: receives library state transition in `post_generation_hook`) |
| `TaggingService` | `services/domain` | Apply calibration + write tags (existing — unchanged except: on completion, transitions library state) |
| `library_if.py` | `interfaces/api/web` | `GET /{id}/pipeline-status`, `POST /{id}/write-tags` endpoints |
| `LibraryPipelineStatusDTO` | `helpers/dto` | Status DTO for pipeline-status response |

### Data Flow

1. **ML completes:** Worker tags last file → queries untagged count → transitions library `ml_running → ml_complete` → calls calibration trigger
2. **Calibration trigger:** `LibraryPipelineService` bulk-transitions all `ml_complete` → `calibrating` → starts `start_histogram_calibration_background()`
3. **Calibration completes:** `post_generation_hook` → bulk-transitions all `calibrating` → `applying` → starts `start_apply_calibration_background()`
4. **Apply completes:** Callback checks `library_auto_write` → transitions to `writing` or `write_ready`
5. **Write completes:** Callback transitions `writing → complete` → triggers Navidrome rescan
6. File state transitions continue to follow ADR-003 axes: `not_tagged → tagged`, `not_calibrated → calibrated`, `tags_not_written → tags_written`

### Concurrency Safety

- State transitions are atomic (REMOVE + INSERT in single AQL transaction) — same pattern as `file_has_state`
- Idempotent transitions: if library is already at target state, transition is a no-op
- `CalibrationService` and `TaggingService` have existing guards against concurrent runs (return "already running")
- Manual user triggers work alongside automation — services reject duplicate runs gracefully

### Complexity Comparison: Derived State vs. Library State Graph

| Dimension | Derived State (old design) | Library State Graph (new design) |
|-----------|---------------------------|----------------------------------|
| Phase query | 4 DB count subqueries + `derive_phase()` | Single INBOUND edge traversal |
| ML completion | 30s poll, check `count_untagged` | Worker-side check post `set_tagged()` |
| Other stages | Polling every 30s | Event-driven (callbacks) |
| Recovery | Automatic (derived from facts) | Startup scan + idempotent transitions |
| State consistency | Always consistent (derived from facts) | Consistent by construction (idempotent transitions) |
| New infrastructure | 1 background thread + 2 bool fields on library doc | 1 edge collection + 1 vertex collection + migration |
| Observability | Must query all libraries to know their phases | Directly traverse from state vertex to find all libraries in that state |
| Latency | Up to 30s delay between event and action | Immediate (event-driven) |
| Concurrency | `_tick_lock` + sequential evaluation | Atomic edge transitions, no lock needed |

---

## Rename: `reconcile_library` → `write_tags_to_files`

This rename aligns the public API with the actual operation (writing curated tags to audio files on disk).

| Layer | Old | New |
|-------|-----|-----|
| Service method | `TaggingService.reconcile_library()` | `TaggingService.write_tags_to_files()` |
| Endpoint route | `POST /{library_id}/reconcile-tags` | `POST /{library_id}/write-tags` |
| Status endpoint | `GET /{library_id}/reconcile-status` | `GET /{library_id}/pipeline-status` (supersedes) |
| Frontend API fn | `reconcileTags()` | `writeTags()` |
| Workflow (unchanged) | `write_file_tags_workflow` | `write_file_tags_workflow` (already correct) |
| DTO | `ReconcileTagsResult` | `WriteTagsResult` |
| Response type | `ReconcileTagsResponse` | `WriteTagsResponse` |

The underlying workflow `write_file_tags_workflow` already has the correct name — only the service, interface, and DTO layers need renaming.

**Behavioral change:** `write_tags_to_files` always runs as a background task. Never inline, regardless of library size. The endpoint returns immediately with a task acknowledgment.

---

## API Surface

### New Endpoint

**`GET /api/web/libraries/{library_id}/pipeline-status`**

Lives on the existing libraries router (`library_if.py`), not a separate pipeline router.

Response body (`PipelineStatusResponse`):

```json
{
  "library_id": "lib-123",
  "state": "applying",
  "untagged_count": null,
  "uncalibrated_count": 42,
  "pending_write_count": null,
  "library_auto_write": false
}
```

Counts are selectively populated based on state:
- `untagged_count`: only when `state == "ml_running"`
- `uncalibrated_count`: only when `state == "applying"`
- `pending_write_count`: only when `state == "write_ready"` or `state == "writing"`

### Renamed Endpoint

**`POST /api/web/libraries/{library_id}/write-tags`** (was `reconcile-tags`)

Triggers `write_tags_to_files` as a background task. Returns immediately. Navidrome rescan fires on background completion.

### Modified Endpoints

**`POST /api/web/libraries`** (create) and **`PUT /api/web/libraries/{id}`** (update):
- Accept `library_auto_write: bool` field

---

## Data Model

### New Collections

**`library_pipeline_states`** (vertex collection — singleton, seeded by migration):

8 vertices with keys: `idle`, `ml_running`, `ml_complete`, `calibrating`, `applying`, `write_ready`, `writing`, `complete`.

**`library_has_pipeline_state`** (edge collection):

`_from: libraries/{id}` → `_to: library_pipeline_states/{state}`

One edge per library. No payload.

### `LibraryPipelineStatusDTO`

```python
@dataclass
class LibraryPipelineStatusDTO:
    library_id: str
    state: str                         # current state vertex key (e.g., "ml_running")
    untagged_count: int | None         # only populated when state == ml_running
    uncalibrated_count: int | None     # only populated when state == applying
    pending_write_count: int | None    # only populated when state == write_ready/writing
    library_auto_write: bool
```

### Library Document Additions

```python
# Single addition to LibraryDict
library_auto_write: bool    # default: False
```

No `initial_calibration_done` — absorbed into the state graph.

### `WriteTagsResult` (renamed from `ReconcileTagsResult`)

Same fields, new name.

---

## Migration

Forward-only migration required:

1. **Create `library_pipeline_states` vertex collection** — seed 8 singleton state vertices (`idle`, `ml_running`, `ml_complete`, `calibrating`, `applying`, `write_ready`, `writing`, `complete`)
2. **Create `library_has_pipeline_state` edge collection**
3. **Add `library_auto_write: false` field** to all existing library documents
4. **Derive initial state for each existing library** — one-time logic using file state counts:
   - No files or no tagged files → `idle`
   - Has untagged files → `ml_running`
   - All tagged, has uncalibrated files → `applying` (calibration data exists if library has calibrated files)
   - All calibrated, has unwritten files → `write_ready`
   - All written → `complete`
5. **Create one `library_has_pipeline_state` edge per library** pointing to its derived initial state

---

## Constants

| Constant | Action | Value | Notes |
|----------|--------|-------|-------|
| `INTERNAL_CALIBRATION_AUTO_RUN` | DELETE | Was `False` | Replaced by event-driven pipeline |
| `INTERNAL_CALIBRATION_CHECK_INTERVAL` | DELETE | Was `604800` | Replaced by event-driven pipeline |
| `INTERNAL_CALIBRATION_MIN_FILES` | KEEP | Existing | Threshold for triggering initial calibration |

No new constants. No `INTERNAL_PIPELINE_POLL_INTERVAL` — there is no poll loop.

---

## Comprehensive Impact Summary

### Backend Changes

| Location | Change |
|----------|--------|
| `nomarr/persistence/database/library_pipeline_states_aql.py` | **NEW** — `LibraryPipelineStatesOperations`: state transitions, state queries, bulk transitions |
| `nomarr/services/infrastructure/pipeline_svc.py` | **NEW** — `LibraryPipelineService`: startup recovery scan, calibration trigger logic, event callback wiring |
| `nomarr/services/domain/tagging_svc.py` | Rename `reconcile_library` → `write_tags_to_files`; make truly async background; move navidrome rescan to completion callback; add library state transition on apply/write completion |
| `nomarr/services/domain/calibration_svc.py` | Add library state transitions in `post_generation_hook` (`calibrating → applying`) |
| `nomarr/components/workers/` or inline in worker | **NEW** — Post-tagging library state check: query untagged count → transition `ml_running → ml_complete` → fire calibration trigger |
| `nomarr/interfaces/api/web/library_if.py` | Rename `reconcile_library_tags` → `write_library_tags`; route `/reconcile-tags` → `/write-tags`; add `GET /{id}/pipeline-status`; deprecate `GET /{id}/reconcile-status` |
| `nomarr/helpers/dto/library_dto.py` | Add `library_auto_write: bool` to `LibraryDict`; add `LibraryPipelineStatusDTO`; rename `ReconcileTagsResult` → `WriteTagsResult` |
| `nomarr/interfaces/api/types/library_types.py` | Add fields to `LibraryResponse`, `CreateLibraryRequest`, `UpdateLibraryRequest`; rename `ReconcileTagsResponse` → `WriteTagsResponse`; add `PipelineStatusResponse` |
| `nomarr/services/domain/library_svc/admin.py` | Add `library_auto_write` to create/update signatures |
| `nomarr/components/library/library_admin_comp.py` | Forward `library_auto_write` in create; insert initial `idle` state edge on library creation |
| `nomarr/components/library/update_library_metadata_comp.py` | Forward `library_auto_write` in update |
| `nomarr/persistence/database/libraries_aql.py` | Add `library_auto_write` to create/update |
| `nomarr/services/infrastructure/config_svc.py` | Delete `INTERNAL_CALIBRATION_AUTO_RUN`, `INTERNAL_CALIBRATION_CHECK_INTERVAL` |
| `nomarr/services/infrastructure/__init__.py` / `nomarr/services/__init__.py` | Remove deleted constant re-exports; add pipeline service export |
| `nomarr/app.py` | Wire `LibraryPipelineService` into startup lifecycle (startup recovery scan) |
| `nomarr/migrations/` | Forward-only migration: create collections, seed states, derive initial state for existing libraries, add `library_auto_write=false` |

### Frontend Changes

| Location | Change |
|----------|--------|
| `frontend/src/shared/types.ts` | Add `libraryAutoWrite: boolean` to `Library` type |
| `frontend/src/shared/api/library.ts` | Rename `reconcileTags` → `writeTags`, `getReconcileStatus` → `getPipelineStatus`; update route strings |
| `frontend/src/shared/api/index.ts` | Update re-exports |
| `frontend/src/features/library/components/LibraryManagement.tsx` | Rename handlers/state; rename "Reconcile" UI copy to "Write Tags"; add `library_auto_write` toggle in library settings |

---

## Design Goals

1. **Zero manual steps after library creation** — add library → full pipeline completes automatically if `library_auto_write=true`
2. **No surprise automation** — new libraries default `library_auto_write=false`; user opts in explicitly
3. **Fail loudly** — no retry logic, no silent backoff; failures surface immediately in logs
4. **Event-driven** — no polling; state transitions fire immediately when their triggering event occurs
5. **Consistent with existing patterns** — library state graph mirrors `file_has_state` (ADR-003): vertex collection + edge collection + atomic transitions
6. **Non-invasive** — delegates to existing `CalibrationService` and `TaggingService` for actual work
7. **Observable** — `GET /{library_id}/pipeline-status` returns stored state + selective counts; INBOUND traversal from any state vertex finds all libraries in that state

---

## Constraints

- Must not duplicate logic in `CalibrationService` or `TaggingService` — delegate only
- Must respect ADR-003 boolean state axes for file state queries
- Must use existing `library_contains_file` edge for per-library file scope
- Must respect existing `file_write_mode` per-library setting
- No ERROR_WAIT or retry states — fail loudly, recover on startup
- No `initial_calibration_done` boolean — state graph absorbs this
- `library_auto_write` boolean stays as library document field (not in state graph)
- Forward-only migration required for new collections and `library_auto_write` field
- Calibration cannot be made per-library (known limitation — not addressed in this design)
- When calibration fires, ALL enabled libraries in `ml_complete` advance simultaneously (global calibration)

---

## Open Questions

1. Should initial calibration require a minimum file count (`INTERNAL_CALIBRATION_MIN_FILES`) before triggering? If yes, what behavior when below threshold — stay in `ml_complete` indefinitely, or require manual calibration?
2. How does the pipeline status display integrate with the library card UI? Is it just a state badge, or a progress indicator?
3. `GET /{id}/reconcile-status` — deprecate silently or return 410 Gone?
4. Should `library_auto_write=true` be settable from the library creation API or only from the update API after first scan?
5. Is the extra DB round-trip in the worker (find library for file + count untagged) acceptable? The AQL is a single-hop INBOUND traversal + a count — negligible per-file cost, and it only fires once per file at tagging completion. The alternative (passing `library_id` through the worker payload) would require changes to `DeferredWrites` or the task queue schema.

---

## Complexity Estimate

**Classification: MEDIUM-LARGE (~580 LOC)**

| Area | Estimated LOC |
|------|---------------|
| `library_pipeline_states_aql.py` (new persistence) | ~120 |
| `pipeline_svc.py` (new — startup recovery + callback wiring) | ~100 |
| Worker post-tagging check + transition | ~40 |
| `tagging_svc.py` (rename + background refactor + state transitions) | ~80 |
| `calibration_svc.py` (state transitions in `post_generation_hook`) | ~20 |
| Library doc field propagation (DTO → component → persistence) | ~80 across 5 files |
| Interface layer (endpoint renames + new pipeline-status endpoint) | ~80 |
| Migration (new collections + seed + derive states + field) | ~60 |

---
