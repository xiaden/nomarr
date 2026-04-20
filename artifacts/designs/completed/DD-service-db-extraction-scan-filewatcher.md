# Service DB Extraction: scan.py and file_watcher_svc.py — Design Document

**Status:** Completed  
**Author:** rnd-dd-author  
**Created:** 2026-04-06  
**Revised:** 2026-04-06 (Amendment 3)

**Related Documents:**

- [ADR-003](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — Pure Boolean State Graph
- [ADR-004](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Schema Refactor V1
- [ADR-013](artifacts/decisions/ADR-013-expand-tagging-service-as-full-tags-vertical-slice.md) — Tag Service Vertical Slice
- [rnd-manager#L31](artifacts/logs/rnd-manager.md#L31) — Initial research request
- [support-researcher#L30](artifacts/logs/support-researcher.md#L30) — Codebase research findings
- [rnd-manager#L32](artifacts/logs/rnd-manager.md#L32) — QA validation corrections
- [rnd-manager#L36](artifacts/logs/rnd-manager.md#L36) — Round 3 amendment request

---

## Scope

nomarr/services/domain/library_svc/scan.py, nomarr/services/infrastructure/file_watcher_svc.py, nomarr/components/library/, nomarr/services/infrastructure/pipeline_svc.py

---

## Problem Statement

Two service files — `scan.py` (LibraryScanMixin) and `file_watcher_svc.py` (FileWatcherService) — make direct database calls that violate the dependency direction principle. Services should delegate persistence to components, not call `db.*` directly.

**scan.py** has 5 methods with direct DB access: 2 are dead code, 1 is a duplicated library-resolution helper, and 2 require new component functions for status/history queries.

**file_watcher_svc.py** has 8 DB calls across 5 methods, including 3 in a startup recovery method that races with the main-thread pipeline recovery (`recover_stale_states`). The service holds `db: Database` in its constructor — all 8 direct `db.collection.*` calls must be extracted so the service delegates to components exclusively. The constructor retains `db` to pass to component functions.

Prior QA noted infrastructure services have systematic direct-DB-call violations. This design addresses the two highest-value targets.

---

## Architecture

## Artifact Constraints

The following prior decisions constrain this design:

- **ADR-003** (Pure Boolean State Graph): Pipeline state is authoritative for "is scanning." Extracted components must not reintroduce thin pass-through wrappers that were already eliminated.
- **ADR-004** (Schema Refactor V1): Scan metadata lives in normalized graph structures. Components must respect `library_scans` model and edge-based relationships.
- **ADR-013** (Tag Service Vertical Slice): Supersedes ADR-007's mixin growth pattern. Do not solve new responsibilities by growing LibraryService — push logic downward into components.
- **DD-api-restructure-regression-fix**: `is_scanning` derives from `library_has_pipeline_state`; `library_scans` is for progress metadata only. Preserve that split.
- **DD-background-task-standardization**: FileWatcherService is a long-lived infrastructure daemon, not a BTS task. This extraction changes DB access ownership only — not lifecycle semantics.

---

## Part 1: scan.py — DB Call Disposition

### Dead Code Deletion

 | Method | Lines | Evidence | Action |
 | -------- | ------- | ---------- | -------- |
 | `_has_healthy_library_workers` | def at L47, body starts L54 | Zero callers across entire codebase | **DELETE** |
 | `_is_scan_running` | def at L66, DB call at L73 | No production callers. Two unit test callers at `tests/unit/services/domain/test_library_svc_scan.py:96` and `:111` — tests must be deleted along with the method. `library_admin_comp._is_scan_running(db)` already exists as the canonical implementation. | **DELETE** |

### Deduplicated Helper

 | Method | Current Implementation | Replacement |
 | -------- | ---------------------- | ------------- |
 | `_get_library_or_error` (L39-44) | `db.libraries.get_library(id)` → None check → raise `ValueError` | `scan_lifecycle_comp.resolve_library_for_scan(db, library_id)` |

**Callers in scan.py:** `get_status()` at L217 and `validate_library_tags()` at L280. NOT `start_quick_scan` or `start_full_scan` — those validate through `scan_setup_workflow`.

**Production caller note:** `validate_library_tags()` is called from `nomarr/interfaces/api/web/library_if.py`, which maps `ValueError` to 404. `LibraryNotFoundError` subclasses `ValueError`, so the mapping remains correct.

**Rationale:** `resolve_library_for_scan` does the same lookup but raises `LibraryNotFoundError`, which subclasses `ValueError` — callers catching `ValueError` remain unaffected. Identical copies exist in `admin.py`, `files.py`, and `query.py` but are explicitly **out of scope** for this PR to keep the refactor bounded.

### New Component Functions for scan.py

#### 1. `get_scanning_library_ids` — in `scan_lifecycle_comp.py`

```python
def get_scanning_library_ids(db: Database) -> set[str]:
    """Return the set of library IDs currently in PIPELINE_SCANNING state."""
```

**Replaces:** `get_status` (L207) inline call to `db.library_pipeline_states.get_libraries_in_state(PIPELINE_SCANNING)`.

**Implementation:** Delegates to `db.library_pipeline_states.get_libraries_in_state(PIPELINE_SCANNING)` and returns the result as `set[str]`. The persistence method already returns `list[str]` of library `_id` values directly — no extraction from state documents is needed. The component's value is providing the correct constant (`PIPELINE_SCANNING`) so callers don't need to import pipeline state constants.

**Placement rationale:** `scan_lifecycle_comp` already owns `is_library_scanning(db, library_id)` for single-library checks. This is the natural multi-library generalization. Publicizing `library_admin_comp._is_scan_running` was considered but rejected because (a) it returns `bool`, not IDs, and (b) it lives in the wrong thematic component.

#### 2. `get_library_scan_histories` — in `scan_lifecycle_comp.py`

```python
def get_library_scan_histories(db: Database, limit: int | None = None) -> list[dict[str, Any]]:
    """Return scan history records for all libraries, including disabled ones.
    
    Args:
        db: Database connection.
        limit: Maximum number of records to return. None for all.
    """
```

**Replaces:** `get_scan_history` (L250) inline call to `db.libraries.list_libraries(enabled_only=False)` plus inline transform logic.

**Output shape:** Returns `list[dict]` with keys `{library_id, name, scanned_at, scan_status}`, matching the current `get_scan_history()` output shape.

**Implementation:** Calls `db.libraries.list_libraries(enabled_only=False)`, projects to `{library_id: lib["_id"], name: lib.get("name", "Unknown"), scanned_at: lib.get("scanned_at"), scan_status: lib.get("scan_status", "idle")}`, applies `limit` slicing if provided, returns structured dicts ready for DTO assembly. Slicing belongs in the component, not the service.

### scan.py After Extraction

`get_status()` assembles `LibraryScanStatusResult` inline from component-provided data. It calls `get_scanning_library_ids()` for the set of currently-scanning libraries and `resolve_library_for_scan()` for the target library lookup. The result DTO is assembled directly in the service method — it is NOT routed through `work_status_comp`, which returns a different DTO (`WorkStatusResult`).

```
scan.py methods:
  start_quick_scan()      → unchanged (validates through scan_setup_workflow, no direct DB)
  start_full_scan()       → unchanged (validates through scan_setup_workflow, no direct DB)
  get_status()            → calls scan_lifecycle_comp.get_scanning_library_ids()
                            + scan_lifecycle_comp.resolve_library_for_scan() (was _get_library_or_error)
                            assembles LibraryScanStatusResult inline
  get_scan_history()      → calls scan_lifecycle_comp.get_library_scan_histories()
  validate_library_tags() → calls scan_lifecycle_comp.resolve_library_for_scan() (was _get_library_or_error)
  _has_healthy_library_workers()  → DELETED
  _is_scan_running()              → DELETED (+ delete 2 unit tests at test_library_svc_scan.py:96,:111)
  _get_library_or_error()         → DELETED (replaced by resolve_library_for_scan)
```

**Zero direct `db.*` calls remain in scan.py after extraction.**

---

## Part 2: file_watcher_svc.py — DB Call Disposition

### Startup Recovery Absorption

**`_reset_stale_scan_statuses`** (3 DB calls at L207, L212, L225) races with `pipeline_svc.recover_stale_states()` on the main thread with no coordination lock. Both perform the same semantic recovery (resetting scan state after unclean shutdown) but write to different stores.

**Decision:** Absorb `_reset_stale_scan_statuses` logic into `LibraryPipelineService.recover_stale_states()` (at `nomarr/services/infrastructure/pipeline_svc.py`).

This eliminates:

- 3 of 8 DB calls in `file_watcher_svc.py`
- A timing hazard between daemon thread and main thread recovery
- Semantic duplication of recovery logic

**Migration:** `recover_stale_states()` gains responsibility for resetting `libraries.scan_status` in addition to pipeline states. For each stale-scanning library, `recover_stale_states()` MUST call `update_scan_status(library_id, status="idle", error="Scan interrupted by server restart")` — without this, the UI-visible `scan_status` metadata would remain stuck showing an active scan. The `file_watcher_svc.py` method `_reset_stale_scan_statuses` is deleted. The daemon thread startup sequence (`sync_watchers`) no longer calls it.

**Return shape:** The existing `dict[str, int]` return shape of `recover_stale_states()` is unchanged. The metadata reset folds into the existing `scanning` counter — each library counted there also gets its `scan_status` reset. No new key is added.

**Phase ordering:** The `_reset_stale_scan_statuses` logic MUST be added to `recover_stale_states()` BEFORE any deletion logic in `sync_watchers()` to avoid a recovery gap where stale states could be missed.

### New Component: `library_watch_config_comp.py`

A new component file at `nomarr/components/library/library_watch_config_comp.py` for the remaining 5 DB calls.

**Why a new file (not extending existing components):**

- `scan_lifecycle_comp` owns scan state transitions — watch mode and library config queries are a different concern
- `library_admin_comp` owns CRUD on libraries — read-only watcher queries don't belong there
- A dedicated `_comp.py` file keeps the watcher's data needs cohesive and under 150 lines

**Write path:** `update_watch_mode` is handled by `UpdateLibraryMetadataComp.update(library_id, watch_mode=new_mode)` — see function detail below. The watch config component owns only read-only queries; writes go through the established metadata update component.

#### Functions

```python
def list_watchable_libraries(db: Database) -> list[dict[str, Any]]:
    """Return libraries eligible for file watching.
    
    Filter: is_enabled AND watch_mode != null AND watch_mode != 'off'.
    Returns projection: {_id, root_path, watch_mode} only.
    """
```

**Replaces:** `sync_watchers` (L250) call to `db.libraries.list_watchable_libraries()`. This is NOT a thin wrapper — the component owns the projection contract (`{_id, root_path, watch_mode}` only), ensuring callers receive a bounded field set rather than full library documents. This is consistent with existing practice like `check_interrupted_scan` in `scan_lifecycle_comp`.

```python
def get_library_watch_config(db: Database, library_id: str) -> dict[str, Any] | None:
    """Get library's watch configuration. Returns None if library not found.
    
    Projected fields: root_path, watch_mode, is_enabled.
    """
```

**Replaces:** `start_watching_library` (L303) and `_polling_loop` (L409) calls to `db.libraries.get_library(library_id)`. Callers only need root path, watch_mode, and is_enabled — this projects just those fields. The `is_enabled` field is required because `_polling_loop()` needs it to decide when to stop watching a library.

#### `update_watch_mode` — routed through `UpdateLibraryMetadataComp`

`update_watch_mode` is **NOT** in `library_watch_config_comp`. It routes through the existing `UpdateLibraryMetadataComp.update(library_id, watch_mode=new_mode)`, which already accepts `watch_mode` as a keyword argument. Creating a separate single-field updater in the watch config component would be a thin wrapper — `UpdateLibraryMetadataComp` is the canonical owner of library field updates.

**Replaces:** `switch_watch_mode` (L520) call to `db.libraries.update_library(library_id, watch_mode=new_mode)`.

**Caller change:** `file_watcher_svc.py` must instantiate or receive `UpdateLibraryMetadataComp(db)` and call `update_library_metadata_comp.update(library_id, watch_mode=new_mode)`. Since the service already holds `self._db`, it can construct the component inline: `UpdateLibraryMetadataComp(self._db).update(library_id, watch_mode=new_mode)`.

This means `library_watch_config_comp` has 2 functions (`list_watchable_libraries` and `get_library_watch_config`), which is acceptable — the component owns read-only watch configuration queries, while writes go through the established metadata update path.

**`__init__.py` update:** `nomarr/components/library/__init__.py` must be updated with re-exports from `library_watch_config_comp.py`: `list_watchable_libraries`, `get_library_watch_config`.

### file_watcher_svc.py Constructor — No Signature Change

**Decision:** Keep `db: Database` in the constructor. The service stores it as `self._db` and passes it to component functions only — never calling `db.collection.*` directly.

**`self.db` → `self._db` rename:** The constructor currently stores `self.db`. This must be renamed to `self._db` to signal it's internal-only. Before renaming, grep for all references to `watcher.db` or `self.db` in `tests/unit/services/test_file_watcher_svc.py` and `nomarr/services/infrastructure/file_watcher_svc.py` to avoid breaking tests or callers that access `watcher.db` directly.

**Rationale:** There are 20 test instantiations in `tests/unit/services/test_file_watcher_svc.py` plus 1 production call in `app.py:312`. Changing the constructor signature would require updating all 21 call sites for zero architectural benefit. The dependency-direction rule is "no direct `db.collection.*` calls in services" — not "services can't hold a db reference." Other services already follow this pattern (hold `db`, pass to components).

**Constructor (unchanged externally):**

```python
def __init__(self, db: Database, library_service, debounce_seconds, event_loop, polling_interval_seconds):
    self._db = db  # Passed to component functions only — no direct db.collection.* calls
```

All remaining call sites become:

```python
library_watch_config_comp.list_watchable_libraries(self._db)
library_watch_config_comp.get_library_watch_config(self._db, library_id)
UpdateLibraryMetadataComp(self._db).update(library_id, watch_mode=mode)
```

### file_watcher_svc.py After Extraction

**Benign race note:** After this extraction, the daemon watcher starts before `recover_stale_states()` runs. A file event during that window hits `except LibraryAlreadyScanningError: continue`, which is correct behavior. A one-line comment is recommended at that `except` clause to prevent it from looking like dead code.

```
file_watcher_svc.py methods:
  _reset_stale_scan_statuses()  → DELETED (absorbed into pipeline_svc.recover_stale_states)
  sync_watchers()               → calls library_watch_config_comp.list_watchable_libraries(db)
  start_watching_library()      → calls library_watch_config_comp.get_library_watch_config(db, id)
  _polling_loop()               → calls library_watch_config_comp.get_library_watch_config(db, id)
  switch_watch_mode()           → calls library_watch_config_comp.get_library_watch_config(db, id)
                                  + UpdateLibraryMetadataComp(db).update(id, watch_mode=mode)
```

**Zero direct `db.collection.*` calls remain in file_watcher_svc.py after extraction.**

---

## Part 3: Startup Order Fix

### Current (problematic)

```
L307: LibraryService created
L312: FileWatcherService(db, library_service) created
L327: daemon thread → sync_watchers() → _reset_stale_scan_statuses()  ← NO LOCK
L346: LibraryPipelineService created
L358: pipeline_svc.recover_stale_states()  ← RACES with above
```

### After (safe)

```
L307: LibraryService created
L312: FileWatcherService(db, library_service) created  ← no recovery here
L346: LibraryPipelineService created
L358: pipeline_svc.recover_stale_states()  ← single recovery point, includes stale scan metadata reset
L327(moved): daemon thread → sync_watchers()  ← no recovery, just watcher setup
```

The daemon thread start can stay in its current position since it no longer does recovery. `sync_watchers()` is safe to call before or after pipeline recovery — it only reads library configs, doesn't write state.

---

## Layer Mapping

 | Component | Layer | File | Responsibility |
 | ----------- | ------- | ------ | ---------------- |
 | `scan_lifecycle_comp` | component | `nomarr/components/library/scan_lifecycle_comp.py` | +2 functions: scanning IDs, scan history |
 | `library_watch_config_comp` | component | `nomarr/components/library/library_watch_config_comp.py` | NEW: 2 read-only functions for watch config queries |
 | `UpdateLibraryMetadataComp` | component | `nomarr/components/library/update_library_metadata_comp.py` | EXISTING: used for `update_watch_mode` via `.update(library_id, watch_mode=...)` |
 | `LibraryScanMixin` | service | `nomarr/services/domain/library_svc/scan.py` | Remove dead code + replace DB calls with component calls |
 | `FileWatcherService` | service | `nomarr/services/infrastructure/file_watcher_svc.py` | Replace all DB calls with component calls, delete recovery method |
 | `LibraryPipelineService` | service | `nomarr/services/infrastructure/pipeline_svc.py` | Absorb stale scan metadata reset into recover_stale_states() |
 | Startup wiring | app | `nomarr/app.py` | Adjust startup order if needed |

---

## Design Goals

1. **Zero direct `db.collection.*` calls** in both `scan.py` and `file_watcher_svc.py` after extraction
2. **Eliminate dead code** in `scan.py` (2 methods with zero callers)
3. **Eliminate timing hazard** between daemon-thread and main-thread recovery
4. **Follow existing conventions**: `_comp.py` suffix, module-level functions, `db: Database` as first param, verb_noun naming
5. **Minimal scope**: Only extract DB calls from these two files. Do not refactor other mixin duplicates, lifecycle semantics, or threading model
6. **No thin wrappers**: Each new component function must add value (projection, aggregation, or domain logic) beyond forwarding to `db.*` — per ADR-003's rejection of pass-through layers

---

## Constraints

- **ADR-003**: No pass-through wrappers that merely forward to `db.*`. Each component function must add value (field projection, aggregation, error handling, or domain logic).
- **ADR-004**: Respect normalized graph schema. `library_scans` is progress metadata; pipeline state is authority for active scanning.
- **ADR-013**: Do not grow LibraryService with more domain logic. Push downward into components.
- **DD-api-restructure-regression-fix**: `is_scanning` derives from pipeline state, not scan doc status.
- **DD-background-task-standardization**: FileWatcherService remains a daemon. This design changes DB access ownership only.
- **Backward compatibility**: `resolve_library_for_scan` raises `LibraryNotFoundError` (subclass of `ValueError`). All callers catching `ValueError` remain unaffected.
- **Scope boundary**: Only the 4 listed mixin copies of `_get_library_or_error` are known. Only scan.py's copy is replaced. The other 3 (admin.py, files.py, query.py) are a separate PR.

---

## Architect's Recommendation: Option C

The Architect analyzed three extraction options and recommends **Option C** for this design:

1. **New lean `library_watch_config_comp.py`** (~60 lines, 2 read-only functions for watch-config queries) + route `update_watch_mode` through existing `UpdateLibraryMetadataComp` — isolates watcher read queries from scan-lifecycle concerns while reusing the established write path.
2. **Absorb `_reset_stale_scan_statuses` into `LibraryPipelineService.recover_stale_states()`** — eliminates duplicate `get_libraries_in_state` query, removes timing hazard between concurrent daemon thread and sync main thread, fixes a latent startup-order issue.
3. **Keep `db` on FileWatcherService constructor** — avoids touching 21 call sites (20 tests + 1 production) for zero architectural benefit.

This combination gives the cleanest layer separation with the smallest blast radius. The design above reflects Option C throughout.

---

## Test Migration Scope

These test files require updates as part of this extraction:

 | File | Changes Required |
 | ------ | ------------------ |
 | `tests/unit/services/domain/test_library_svc_scan.py` | Delete `_is_scan_running` tests (L96, L111). Update `get_status` tests for component-delegated implementation. |
 | `tests/unit/services/test_file_watcher_svc.py` | Constructor signature unchanged — no updates to 20 instantiation sites. Delete `TestResetStaleScanStatuses` class (L629-673) since `_reset_stale_scan_statuses` is absorbed into pipeline_svc. Grep for `watcher.db` references before `self.db` → `self._db` rename. |
 | `tests/unit/services/infrastructure/test_pipeline_svc.py` | Add tests for absorbed stale scan recovery (existing call sites at L97, L121, L148, L169, L338, L370 need coverage for new recovery responsibility). |
 | `tests/integration/test_pipeline_integration.py` | Verify integration coverage for absorbed recovery logic (existing call at L420). |
 | `tests/unit/components/library/test_scan_lifecycle_comp.py` | Extend with tests for new `get_scanning_library_ids` and `get_library_scan_histories` functions. |
 | `tests/unit/components/library/test_library_watch_config_comp.py` | **NEW**: Unit tests for `list_watchable_libraries` and `get_library_watch_config`. |

---

## Out-of-Scope Infrastructure Services

The following infrastructure services have the same direct-DB-call pattern but are **explicitly out of scope** for this design. They should be addressed in a separate extraction effort:

 | Service | File | Direct DB Calls |
 | --------- | ------ | ----------------- |
 | HealthMonitorService | `nomarr/services/infrastructure/health_monitor_svc.py` | 1 call |
 | MLService | `nomarr/services/infrastructure/ml_svc.py` | 4 calls |
 | LibraryPipelineService | `nomarr/services/infrastructure/pipeline_svc.py` | ~20 calls |
 | WorkerSystemService | `nomarr/services/infrastructure/worker_system_svc.py` | 6 calls |
 | KeysService | `nomarr/services/infrastructure/keys_svc.py` | 12 calls (uses `self._db`) |

These are noted here for future planning visibility. Each would follow a similar component-extraction pattern.

**Note:** `pipeline_svc.py` has growing DB responsibility (~20 direct calls, plus the stale scan recovery absorbed by this design). This is acceptable: `pipeline_svc` is an infrastructure service whose primary job is managing pipeline state persistence. Its direct DB access is a systemic pattern across infrastructure services, not something this DD needs to fix. A dedicated extraction effort for infrastructure services (listed above) would address this holistically.

---

## Import Side Effects

`scan.py` has **no runtime persistence imports** — only `TYPE_CHECKING` imports. There are no import-side-effect concerns for this extraction.

---

## Open Questions

1. ~~**Status DTO assembly split**~~: Resolved — `get_scan_status_data` was removed. `get_status()` calls `get_scanning_library_ids()` + `resolve_library_for_scan()` and assembles `LibraryScanStatusResult` inline. No third function needed.

2. ~~**`recover_stale_states` scope**~~: Resolved — `recover_stale_states()` MUST call `update_scan_status(library_id, status="idle", error="Scan interrupted by server restart")` for each stale-scanning library. Without this, the UI-visible `scan_status` metadata remains stuck. See Part 2: Startup Recovery Absorption for full details.

3. ~~**Component module injection pattern**~~: Resolved — keeping `db` on `FileWatcherService` and passing it to component functions (Option C). If a stricter "no db on service" pattern emerges from future ADRs, this can be refactored to use partial application.

---

## Amendment Log

**Amendment 1** (2026-04-06): Initial QA corrections — line number fixes, factual corrections from codebase verification.

**Amendment 2** (2026-04-06): 26 fixes applied across 4 severity tiers:

- **MUST-FIX (4):** Corrected pipeline_svc path (M-1). Removed unnecessary `get_scan_status_data` function (M-2). Fixed `get_status()` to assemble `LibraryScanStatusResult` inline instead of routing through `work_status_comp` (M-3). Committed `recover_stale_states` scan_status reset as a firm decision (M-4).
- **SHOULD-FIX (6):** Renamed `resolve_library_watch_config` → `get_library_watch_config` (S-1). Dropped redundant `get_library_watch_mode` (S-2). Added `__init__.py` re-export step (S-3). Added projection for `list_watchable_libraries` (S-4). Called out `self.db` → `self._db` rename with grep step (S-5). Added `limit` param to `get_library_scan_histories` (S-6).
- **PATTERN ENFORCER (5):** Added `is_enabled` to watch config projection (PE-1). Fixed `list_watchable_libraries` filter semantics (PE-2). Specified `recover_stale_states` return shape (PE-3). Named `validate_library_tags` production caller (PE-4). Justified `update_watch_mode` vs `UpdateLibraryMetadataComp.update()` (PE-5).
- **FACTUAL + OPTIONAL (11):** Fixed 8 line number errors. Corrected `start_scan()` to `start_quick_scan()`/`start_full_scan()`. Added phase ordering note (O-1). Added benign race comment note (O-2). Renamed component file to `library_watch_config_comp.py` (O-3).

**Amendment 3** (2026-04-06): 7 fixes from PatternEnforcer Round 3 (source: rnd-manager#L36):

- **FAIL-1:** Fixed internal contradiction — "eliminate this dependency entirely" → "eliminate direct `db.collection.*` calls." Constructor retains `db` to pass to components.
- **FAIL-2:** Rerouted `update_watch_mode` through existing `UpdateLibraryMetadataComp.update()` instead of new thin wrapper. `library_watch_config_comp` reduced to 2 read-only functions. Made `list_watchable_libraries` projection value explicit.
- **FAIL-3:** Fixed `get_scanning_library_ids` implementation — persistence already returns `list[str]`, no extraction needed. Component value is providing `PIPELINE_SCANNING` constant.
- **FAIL-4:** Added test coverage entries for `test_scan_lifecycle_comp.py` (extension) and `test_library_watch_config_comp.py` (new).
- **WARN-1:** Specified `get_library_scan_histories` output shape: `{library_id, name, scanned_at, scan_status}`.
- **WARN-2:** Added `pipeline_svc.py` growing DB responsibility acknowledgment as acceptable out-of-scope systemic pattern.
- **WARN-3:** Fixed 6 malformed markdown links in Related Documents (empty display text).

---
