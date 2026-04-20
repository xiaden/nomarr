# File Splitting Refactor — 5 Hard-Limit Violations — Design Document

**Status:** Completed  
**Author:** RnD-DDAuthor  
**Created:** 2026-04-08  

---

## Scope

nomarr/persistence/database/file_states_aql.py, nomarr/services/domain/tagging_svc.py, nomarr/interfaces/api/web/library_if.py, nomarr/services/infrastructure/workers/discovery_worker.py, nomarr/services/infrastructure/worker_system_svc.py

---

## Problem Statement

Five files exceed the project's hard line-count limits, blocking further development per project conventions:

 | File | Lines | Limit | Over |
 | ------ | ------- | ------- | ------ |
 | `persistence/database/file_states_aql.py` | 981 | 600 | +63% |
 | `services/domain/tagging_svc.py` | 790 | 500 | +58% |
 | `interfaces/api/web/library_if.py` | 754 | 500 | +51% |
 | `services/infrastructure/workers/discovery_worker.py` | 662 | 500 | +32% |
 | `services/infrastructure/worker_system_svc.py` | 576 | 500 | +15% |

Each split must produce modules that own meaningful logic — no thin passthroughs (ADR-003). The project already has two validated split patterns: the `library_files_aql/` subpackage (persistence mixin composition) and the `library_svc/` package (service mixin composition). These patterns are the template for splits 1 and 2.

---

## Architecture

## Split Strategy

### Split 1: `file_states_aql.py` → `file_states_aql/` Subpackage

**Pattern:** Follow `library_files_aql/` — mixin classes composed into `FileStatesOperations` in `__init__.py`.

**Current class:** `FileStatesOperations` (1 class, ~35 methods, 981 lines)

**Proposed modules:**

 | Module | Mixin Class | Methods | Rationale |
 | -------- | ------------- | --------- | ----------- |
 | `transitions.py` | `FileStatesTransitionsMixin` | `_transition_state`, `set_tagged`, `set_too_short`, `set_calibrated`, `set_tags_written`, `set_tags_current`, `set_scanned`, `set_vectors_extracted`, `set_errored`, `set_not_tagged`, `set_not_too_short`, `set_not_calibrated`, `set_tags_not_written`, `set_tags_stale`, `set_not_scanned`, `set_not_vectors_extracted`, `set_not_errored` | Core state machine — all single-file transitions share common `_transition_state` logic |
 | `bulk.py` | `FileStatesBulkMixin` | `bulk_set_not_calibrated`, `bulk_set_tags_stale`, `bulk_set_scanned`, `bulk_set_not_vectors_extracted`, `bulk_set_not_errored` | Batch operations with different AQL patterns (iterate collections vs. per-ID) |
 | `init.py` | `FileStatesInitMixin` | `initialize_file_states`, `initialize_file_states_batch` | File lifecycle entry — creating edges for new files |
 | `queries.py` | `FileStatesQueriesMixin` | `discover_next_untagged_file`, `get_untagged_file_ids`, `count_untagged_files`, `count_uncalibrated_files`, `get_errored_file_ids`, `count_errored_files`, `get_uncalibrated_tagged_file_ids`, `get_stale_file_ids`, `get_calibration_status_by_library`, `library_has_tagged_files`, `get_files_with_incomplete_tags` | Read-only queries — traversals and aggregations |
 | `reset.py` | `FileStatesResetMixin` | `clear_tagged_batch`, `clear_all_states`, `clear_all_states_batch`, `count_pending_tag_writes`, `get_pending_tag_write_file_ids` | Cleanup/reset operations — removing and counting pending edges |

**`__init__.py`** — Aggregator:

```python
class FileStatesOperations(
    FileStatesTransitionsMixin,
    FileStatesBulkMixin,
    FileStatesInitMixin,
    FileStatesQueriesMixin,
    FileStatesResetMixin,
):
    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
```

**Constants:** Module-level constants (`STATE_TAGGED`, `AXIS_PAIRS`, etc.) move to a `_constants.py` or stay in `__init__.py` and are imported by mixins. Since mixins reference these constants, co-locating them in `__init__.py` and importing from the package root keeps things clean.

**External callers:** No changes. All callers access via `db.file_states.*` — the `Database.file_states` attribute is typed as `FileStatesOperations` and the import in `db.py` changes from `from nomarr.persistence.database.file_states_aql import FileStatesOperations` to `from nomarr.persistence.database.file_states_aql import FileStatesOperations` (same path, now resolves to the package `__init__`).

**Other imports needing update:**

- `tests/unit/persistence/database/test_file_states_aql.py` — imports `FileStatesOperations` and constants directly
- `nomarr/migrations/V023_library_pipeline_states.py` — imports constants
- `nomarr/components/platform/arango_bootstrap_comp.py` — imports `ALL_STATE_VERTICES`

All three can continue importing from `nomarr.persistence.database.file_states_aql` since the package `__init__.py` will re-export everything.

**Required re-exports in `file_states_aql/__init__.py`** (exhaustive list):

- `FileStatesOperations` — imported by `nomarr/persistence/db.py`, tests
- All `STATE_*` constants (`STATE_TAGGED`, `STATE_SCANNED`, `STATE_CALIBRATED`, `STATE_VECTORS_EXTRACTED`, `STATE_TOO_SHORT`, `STATE_ERRORED`, `STATE_TAGS_WRITTEN`, `STATE_TAGS_CURRENT`) — imported by `nomarr/migrations/V023_library_pipeline_states.py`
- `ALL_STATE_VERTICES` — imported by `nomarr/components/platform/arango_bootstrap_comp.py`
- `AXIS_PAIRS` — if publicly used by callers outside the package

---

### Split 2: `tagging_svc.py` → `tagging_svc/` Package

**Pattern:** Follow `library_svc/` — mixin classes composed into `TaggingService` in `__init__.py`.

**Current class:** `TaggingService` (1 class, ~30 methods, 790 lines) plus 4 TypedDicts and a config dataclass.

**Proposed modules:**

 | Module | Mixin Class | Methods | Rationale |
 | -------- | ------------- | --------- | ----------- |
 | `apply.py` | `TaggingApplyMixin` | `tag_file`, `tag_library`, `start_apply_calibration_background`, `_run_apply_calibration`, `_update_apply_progress`, `_clear_apply_progress`, `is_apply_running`, `_get_apply_status`, `_get_apply_progress`, `get_apply_combined_status`, `get_calibration_status` | Calibration application lifecycle — tightly coupled private state (`_apply_progress_lock`, BTS task management) |
 | `write.py` | `TaggingWriteMixin` | `read_file_tags`, `remove_file_tags`, `write_tags_to_files`, `start_write_tags_background`, `mark_tags_stale`, `get_reconcile_status` | File tag I/O — read/write/reconcile operations |
 | `curation.py` | `TaggingCurationMixin` | `_reject_nom_prefix`, `_get_tag_or_error`, `rename_tag`, `merge_tags`, `split_tag`, `update_file_tags` | Tag management — rename/merge/split with nom: prefix enforcement (ADR-009) |
 | `query.py` | `TaggingQueryMixin` | `list_tag_values`, `get_tag_songs`, `get_pending_commit_count`, `commit_pending_tags`, `get_unique_tag_keys`, `get_unique_tag_values`, `get_unique_mood_values`, `get_file_tags`, `cleanup_orphaned_tags`, `search_files_by_tag` | Read/query operations |
 | `config.py` | — | `TaggingServiceConfig`, `ApplyCalibrationResultDict`, `ApplyCalibrationStatusDict`, `ApplyCalibrationProgressDict`, `ApplyCalibrationCombinedStatusDict`, `CALIBRATION_APPLY_TASK_ID` | Configuration and type definitions |

**`__init__.py`** — Aggregator:

```python
class TaggingService(
    TaggingApplyMixin,
    TaggingWriteMixin,
    TaggingCurationMixin,
    TaggingQueryMixin,
):
    def __init__(self, database, cfg, bts, config_service, library_service=None):
        ...  # existing __init__ body
```

**mypy mixin caveat:** The `_reject_nom_prefix` static method and `_get_tag_or_error` instance method are used by `curation.py` methods. They stay in `curation.py` since that's their only caller. The `namespace` property is used across mixins — it stays in `__init__.py` on the composed class or each mixin defines a protocol/type stub. Per the warning from prior work, **do NOT centralize helpers across mixins** — if a mixin needs `_get_tag_or_error`, define it locally in that mixin.

**External callers:** No changes. All callers access `TaggingService` via DI and `from nomarr.services.domain.tagging_svc import TaggingService` continues to work since the package `__init__.py` re-exports it.

**Required re-exports in `tagging_svc/__init__.py`** (exhaustive list):

- `TaggingService` — imported by `nomarr/app.py`, tests
- `TaggingServiceConfig` — imported by `nomarr/app.py`
- `CALIBRATION_APPLY_TASK_ID` — imported by `nomarr/services/infrastructure/pipeline_svc.py`
- `ApplyCalibrationCombinedStatusDict` — imported by `nomarr/interfaces/api/web/calibration_if.py`

---

### Split 3: `library_if.py` → Three Router Modules

**Pattern:** Interfaces use FastAPI `APIRouter`, not mixin classes. Split into separate router modules, each with its own `APIRouter` instance, all mounted via `router.py`.

**Current file:** 754 lines, single `APIRouter(prefix="/library")`, ~25 endpoint functions, 6 Pydantic models.

**Proposed modules:**

 | Module | Endpoints | Lines (est.) | Rationale |
 | -------- | ----------- | ------------- | ----------- |
 | `library_if.py` | `list_libraries`, `get_library`, `create_library`, `update_library`, `delete_library`, `web_library_stats`, `get_library_vector_config`, `update_library_vector_config`, `get_library_vector_stats` | ~250 | Library entity CRUD + stats + vector config |
 | `library_files_if.py` | `search_library_files`, `get_files_by_ids`, `search_files_by_tag`, `get_unique_tag_keys`, `get_unique_tag_values`, `get_unique_mood_values`, `cleanup_orphaned_tags`, `get_file_tags`, `get_errored_files`, `retry_errored_files` | ~250 | File search/query + tag discovery + error management |
 | `library_scan_if.py` | `scan_library_quick`, `scan_library_full`, `reconcile_library_paths`, `write_library_tags`, `get_library_pipeline_status`, `update_write_mode`, `validate_library_tags` | ~250 | Scan/pipeline/write operations |

**Router prefix strategy:** All three routers use `prefix="/library"` and `tags=["Library"]` to maintain the same URL structure. The `router.py` aggregator changes from one `library.router` include to three:

```python
from nomarr.interfaces.api.web import library_if, library_files_if, library_scan_if
router.include_router(library_if.router)
router.include_router(library_files_if.router)
router.include_router(library_scan_if.router)
```

**Pydantic models:** `VectorConfigResponse`, `VectorConfigUpdate`, `VectorStatsItem`, `LibraryVectorStatsResponse` stay in `library_if.py` (only used there). `FileIdsRequest`, `TagSearchRequest` move to `library_files_if.py` (only used there).

**Router wiring:** `nomarr/interfaces/api/web/router.py` must register all 3 routers. All use prefix `/library` — the prefix stays on each router definition, sub-routers have no additional prefix:

```python
from nomarr.interfaces.api.web import library_if, library_files_if, library_scan_if
router.include_router(library_if.router)       # CRUD + vectors
router.include_router(library_files_if.router)  # file operations
router.include_router(library_scan_if.router)   # scan operations
```

**Test import updates:** 4 test files import `library_if.router` directly and must be updated after the split:

- `tests/integration/test_library_endpoints.py` — update imports to match endpoint ownership
- `tests/integration/test_reconcile_endpoint.py` — scan endpoints → import from `library_scan_if.router`
- `tests/unit/interfaces/web/test_library_auto_write_toggle.py` — scan/write endpoints → import from `library_scan_if.router`
- `tests/unit/interfaces/web/test_pipeline_endpoint.py` — pipeline endpoints → import from `library_scan_if.router`

After the split:

- Tests for scan/pipeline/write endpoints should import from `library_scan_if.router`
- Tests for file search/tag endpoints should import from `library_files_if.router`
- Tests for library CRUD/vector endpoints keep importing from `library_if.router`

---

### Split 4: `discovery_worker.py` — Internal Method Extraction (No Package Split)

**Pattern:** This is NOT a mixin or package split. The `run()` method is 425 lines — it needs decomposition into private helper methods within the same class. Module-level functions (`_check_idle_pipeline_completion`, `_malloc_trim`, `_execute_deferred_writes`) already exist and stay as-is.

**Current structure:** `DiscoveryWorker` class (6 class methods: `__init__`, `_configure_subprocess_logging`, `_send_health_frame`, `_health_writer_loop`, `run`, `stop`) + 4 module-level functions (`_check_idle_pipeline_completion`, `_malloc_trim`, `_execute_deferred_writes`, `create_discovery_worker`). All 6 class methods and all 4 module-level functions remain in `discovery_worker.py` — this is same-file extraction, not a package split.

**Proposed extraction from `run()`:**

 | New Private Method | Responsibility | Lines (est.) |
 | ------------------- | ---------------- | ------------- |
 | `_preflight_and_connect` | Late imports, health thread start, ML check, DB connect, worker context, stale promise cleanup, config reconstruction | ~80 |
 | `_evict_idle_cache` | ONNX cache eviction on idle timeout + malloc_trim | ~15 |
 | `_maybe_spawn_idle_promotion` | Idle vector promotion thread spawn logic | ~30 |
 | `_warm_onnx_cache` | Lazy ONNX cache warmup (VRAM probe, cache creation, fleet logging) | ~60 |
 | `_check_resource_headroom` | Per-file resource check (VRAM/RAM budget, recovery state entry) | ~30 |
 | `_process_claimed_file` | File doc fetch, process_file_workflow call, result dispatch (skip/deferred/direct) | ~60 |
 | `_handle_process_error` | Error logging, set_errored, release_claim, consecutive error check | ~20 |

**`run()` becomes:** A compact orchestration loop (~80 lines) that calls these helpers in sequence.

**Note:** The 4 module-level functions (`_check_idle_pipeline_completion`, `_malloc_trim`, `_execute_deferred_writes`, `create_discovery_worker`) are already well-extracted and stay unchanged. The remaining class methods (`__init__`, `_configure_subprocess_logging`, `_send_health_frame`, `_health_writer_loop`, `stop`) also stay unchanged — only `run()` is decomposed.

**External callers:** None — `run()` is called by `multiprocessing.Process` internally. The class interface doesn't change.

---

### Split 5: `worker_system_svc.py` — Internal Method Extraction (No Package Split)

**Pattern:** Like split 4, this is internal decomposition, not a package split. At 576 lines (+15% over), the goal is modest reduction — extract the largest methods into helpers.

**Current structure:** `WorkerSystemService` class (14 methods, all remain in `worker_system_svc.py`):

- Init: `__init__`
- Resource Management: `_check_gpu_capability`, `_run_admission_control` (~65 lines) — remain in `worker_system_svc.py` for simplicity
- ComponentLifecycleHandler: `on_status_change`, `_restart_worker` (~130 lines)
- Control Methods: `is_worker_system_enabled`, `enable_worker_system`, `disable_worker_system` (~15 lines)
- Worker Lifecycle: `start_all_workers`, `stop_all_workers` (~100 lines)
- Status: `is_running`, `get_workers_status`, `get_resource_status`, `cleanup_stale_claims` (~50 lines)

All methods stay in `worker_system_svc.py` — this is internal method extraction only.

**Proposed extraction:**

 | Target | Action | Rationale |
 | -------- | -------- | ----------- |
 | `_restart_worker` (80 lines) | Extract `_drain_old_worker(worker, timeout)` helper | The old-worker drain + force-kill sequence is self-contained |
 | `on_status_change` → dead handling (50 lines) | Extract `_handle_worker_death(component_id)` | Complex claim release + VRAM cleanup + restart policy logic |
 | `start_all_workers` → worker spawn loop (40 lines) | Extract `_spawn_worker(index, tier_selection)` | Pipe creation + worker creation + health registration per worker |

These three extractions should bring the file to ~480 lines, comfortably under 500.

**External callers:** No public API changes.

---

## Design Goals

1. Bring all 5 files under their respective hard line-count limits
2. Follow existing split patterns (persistence subpackage, service mixin package) verbatim
3. Every resulting module must own meaningful logic — no thin passthroughs (ADR-003)
4. Preserve all public APIs and import paths via re-exports
5. Minimize caller churn — external code should not need to change import paths

---

## Constraints

### Binding Constraints (from ADRs and prior work)

- **ADR-003:** No passthrough modules. Each split module must own real logic.
- **ADR-004:** Persistence splits must preserve normalized edge/document ownership from V021.
- **ADR-009:** nom: prefix rejection logic stays co-located with curation methods.
- **ADR-013:** Tag-domain responsibilities belong in TaggingService, not LibraryService. The tagging_svc split does not change domain ownership.
- **mypy mixin caveat:** Do NOT centralize helpers across mixins. Define `_get_tag_or_error` locally per mixin if needed. Cross-mixin method resolution causes mypy regressions.

### Non-Functional

- Each resulting file should target the "consider" threshold (300 for services/components, 400 for persistence) where possible, with hard ceiling at the MUST limit.
- Test files that import directly from split modules need import path updates.
- Splits 4 and 5 are internal refactors — no test changes expected unless tests mock private methods.

---

## Open Questions

1. **Constants placement for `file_states_aql/`:** Should `STATE_TAGGED`, `AXIS_PAIRS`, `ALL_STATE_VERTICES` etc. live in `__init__.py` or a dedicated `_constants.py`? The `library_files_aql/` pattern doesn't have a constants module, but `file_states_aql` has significantly more constants (~20). **Recommendation:** Use `_constants.py` for cleanliness, re-export from `__init__.py` for backward compatibility.

2. **`namespace` property in TaggingService mixins:** Multiple mixins use `self.namespace`. Should this be on the composed class only (requiring `self: TaggingService` type annotations on mixin methods) or duplicated? **Recommendation:** Keep `namespace` property on the composed class in `__init__.py` and use `self.namespace` naturally — mypy resolves this fine since the final composed class has it.

3. ~~**Admission control extraction for worker_system_svc**~~ — **Resolved:** `_check_gpu_capability` and `_run_admission_control` remain in `worker_system_svc.py` for simplicity. The three proposed helper extractions (`_drain_old_worker`, `_handle_worker_death`, `_spawn_worker`) are sufficient to bring the file under the 500-line limit.

---
