# File Splitting Refactor — Contracts Ledger

**Design Doc:** `artifacts/designs/pending/DD-file-splitting-refactor.md`

## Architectural Rules

- ADR-003: No passthrough wrappers — each split module must own real logic
- ADR-004: Persistence splits preserve V021 graph normalization
- ADR-009: `nom:` prefix rejection stays co-located with curation methods
- ADR-013: Tag-domain responsibilities stay in TaggingService
- ADR-021: File length limits — the governing ADR for this refactor
- Mypy mixin caveat: Do NOT centralize helpers across mixins; define locally per mixin

## Collections & Methods

### Plan A: Persistence Subpackage

**Creates (internal to package — no new public API):**

- `file_states_aql/_constants.py` — all STATE_* constants, AXIS_PAIRS, ALL_STATE_VERTICES
- `file_states_aql/transitions.py` — FileStatesTransitionsMixin (_transition_state + 18 set/unset methods)
- `file_states_aql/bulk.py` — FileStatesBulkMixin (5 bulk_set_* methods)
- `file_states_aql/init.py` — FileStatesInitMixin (initialize_file_states, initialize_file_states_batch)
- `file_states_aql/queries.py` — FileStatesQueriesMixin (11 query methods)
- `file_states_aql/reset.py` — FileStatesResetMixin (5 reset/count methods)
- `file_states_aql/__init__.py` — FileStatesOperations (composed class, re-exports all public symbols)

**Calls (existing, unchanged):** All callers use `db.file_states.*` — no import path changes

### Plan B: Tagging Service Mixin Package

**Creates (internal to package — no new public API):**

- `tagging_svc/config.py` — TaggingServiceConfig, 4 TypedDicts, CALIBRATION_APPLY_TASK_ID
- `tagging_svc/apply.py` — TaggingApplyMixin (11 calibration lifecycle methods)
- `tagging_svc/write.py` — TaggingWriteMixin (6 file tag I/O methods)
- `tagging_svc/curation.py` — TaggingCurationMixin (4 tag management + 2 local helpers)
- `tagging_svc/query.py` — TaggingQueryMixin (10 query methods)
- `tagging_svc/__init__.py` — TaggingService (composed class, re-exports public symbols)

**Calls (existing, unchanged):** All 15 import sites use `from nomarr.services.domain.tagging_svc import ...`

### Plan C: Worker Internal Extraction

**Creates (private methods only — no public API):**

- `DiscoveryWorker._preflight_and_connect()`, `._evict_idle_cache()`, `._maybe_spawn_idle_promotion()`, `._warm_onnx_cache()`, `._check_resource_headroom()`, `._process_claimed_file()`, `._handle_process_error()`
- `WorkerSystemService._drain_old_worker()`, `._handle_worker_death()`, `._spawn_worker()`

**Calls:** No external changes — internal decomposition only

### Plan D: Library Interface Router Split

**Creates:**

- `library_files_if.py` — APIRouter with file/tag endpoints, FileIdsRequest, TagSearchRequest
- `library_scan_if.py` — APIRouter with scan/pipeline/write endpoints

**Modifies:**

- `library_if.py` — reduced to CRUD + vector config endpoints
- `router.py` — includes 3 routers instead of 1
- 4 test files — updated imports to match endpoint ownership

## API Contracts

No API changes — all splits preserve existing public APIs.

## DTOs

No DTO changes — TypedDicts and Pydantic models relocate but keep identical signatures.

## Decisions

- Constants in `file_states_aql/` go to `_constants.py`, re-exported from `__init__.py`
- `namespace` property stays on composed `TaggingService` class in `__init__.py`
- Helper methods (`_get_tag_or_error`, `_reject_nom_prefix`) stay local to their mixin
