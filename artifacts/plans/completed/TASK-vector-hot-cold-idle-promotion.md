# Task: Automatic Hot→Cold Vector Promotion in Worker Idle Loop

## Problem Statement

Workers write embedding vectors to per-library hot collections
(`vectors_track_hot__{backbone_id}__{library_key}`) during ML inference. After a scan completes,
those vectors sit in hot indefinitely — vector similarity search is broken until an operator
manually triggers `promote_and_rebuild_workflow` via the API or CLI.

The root cause is lifecycle coupling: the operation that enables search (hot→cold promotion + HNSW
index rebuild) is detached from the operation that produces the data (tagging). Operators discover
the problem only when a similarity search returns no results.

The fix: when a worker exhausts its work queue (truly idle — `discover_and_claim_file` returns
`None`), it should automatically trigger promote-and-rebuild for any backbone+library that has
pending hot vectors. This requires:

1. Detecting "truly idle" (not just momentarily between files)
2. Coordinating across workers so only one runs the expensive rebuild at a time
3. Not blocking the worker from resuming tagging if new files arrive
4. Reusing the existing `promote_and_rebuild_workflow` exactly as-is (it is already idempotent and
   covers all steps: drain, drop index, rebuild)

### Architecture Context

- `DiscoveryWorker.run()` in `nomarr/services/infrastructure/workers/discovery_worker.py` has an
  idle branch (`file_id is None`) that currently only evicts the ONNX cache on timeout.
- `promote_and_rebuild_workflow(db, backbone_id, library_key, nlists, models_dir)` in
  `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py` is convergent and idempotent.
  Exits early if hot is empty and cold index already exists.
- `compute_nlists(doc_count, group_size=15)` in `nomarr/helpers/vector_params_helper.py` is the
  shared nlists formula — `VectorMaintenanceService.calculate_optimal_nlists` already delegates to
  it. **No new helper needed.**
- `discover_backbones(models_dir)` from `nomarr/components/ml/onnx/ml_discovery_comp` returns
  unique backbone IDs from the filesystem. Cheaper than `discover_heads` (no DB query).
- Hot collections use per-library naming: `vectors_track_hot__{backbone_id}__{library_key}`
  (V018 split). Checking hot count requires both backbone and library:
  `db.register_vectors_track_backbone(backbone_id, library_key).count()`.
- Per-library `vector_group_size` can be read directly from the library document via
  `db.libraries.get_library(library_key)` (persistence-layer access, no ConfigService dependency).
- Python-arango connection pooling is thread-safe within a single process. The `Database` instance
  created in `run()` can be safely passed to the promotion thread.
- Coordination lock must be DB-level: workers run as separate OS processes (no shared memory).
  Lock key encodes both backbone and library: `{backbone_id}__{library_key}`.
- `idle_consecutive_polls` must increment **as the first statement** of the idle branch, before
  cache eviction and before `time.sleep`, so every idle poll is counted unconditionally.
- Latest migration is V018 (`split_vectors_per_library`). New migration will be V019.

## Phases

### Phase 1: DB-Level Promotion Lock
- [x] Create `nomarr/migrations/V019_add_vector_promotion_locks.py` with `SCHEMA_VERSION_BEFORE = 18`, `SCHEMA_VERSION_AFTER = 19` that creates the `vector_promotion_locks` collection if it does not exist. Follow the migration pattern from existing collection-creation migrations.
    **Notes:** Created nomarr/migrations/V019_add_vector_promotion_locks.py (53 lines). SCHEMA_VERSION_BEFORE=18, SCHEMA_VERSION_AFTER=19. Creates vector_promotion_locks collection idempotently. Lint clean.
- [x] Create `nomarr/persistence/database/vector_promotion_lock_aql.py` with `VectorPromotionLockOperations` class. Collection name: `vector_promotion_locks`. Lock key format: `{backbone_id}__{library_key}`. Document schema: `{ _key, locked_by: worker_id, locked_at: epoch_ms }`. Implement: `try_acquire_lock(backbone_id, library_key, worker_id) -> bool` using AQL INSERT with `ignoreErrors: true` (returns True if inserted); `release_lock(backbone_id, library_key, worker_id) -> None` with DELETE guarded by `locked_by == worker_id`; `force_release_lock(backbone_id, library_key) -> None` as unconditional DELETE by key; `get_stale_locks(stale_after_ms) -> list[tuple[str, str]]` returning `(backbone_id, library_key)` pairs whose `locked_at` exceeds the threshold.
    **Notes:** Created nomarr/persistence/database/vector_promotion_lock_aql.py (177 lines). VectorPromotionLockOperations with try_acquire_lock (AQL INSERT ignoreErrors), release_lock (locked_by guard), force_release_lock (unconditional), get_stale_locks (returns (backbone_id, library_key) tuples). Lint clean.
- [x] Register `vector_promotion_locks: VectorPromotionLockOperations` as attribute on `Database.__init__` and export `VectorPromotionLockOperations` from `nomarr/persistence/database/__init__.py`.
    **Notes:** Added import + attribute in db.py (line 32 import, line 149 init). Added export in database/__init__.py (line 26 import, line 41 __all__). Lint clean on both files.
- [x] Run `lint_project_backend(path="nomarr/persistence")` and fix all errors.
    **Notes:** lint_project_backend(path="nomarr/persistence") \u2014 0 errors, 8 files checked.

### Phase 2: Idle Promotion Component
- [x] Create `nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py`. Module docstring must state that `db` is safe to share with the calling thread due to python-arango connection pooling. Implement `list_hot_vector_targets(db: Database, models_dir: str) -> list[tuple[str, str]]`: calls `discover_backbones(models_dir)` for backbone IDs, `db.libraries.list_libraries()` for library keys, then for each `(backbone_id, library_key)` pair checks `db.db.has_collection(f"vectors_track_hot__{backbone_id}__{library_key}")` and if present calls `db.register_vectors_track_backbone(backbone_id, library_key).count()`. Returns pairs where count > 0.
    **Notes:** Created nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py (65 lines). list_hot_vector_targets iterates discover_backbones() x list_libraries(), checks has_collection + count() > 0. Module docstring documents thread safety. Lint clean.
- [x] Implement `run_idle_promotion(db: Database, worker_id: str, models_dir: str) -> int`: (a) calls `list_hot_vector_targets`; (b) calls `db.vector_promotion_locks.get_stale_locks(stale_after_ms=600_000)` and force-releases each; (c) for each target, calls `try_acquire_lock`; (d) if acquired, computes nlists via private `_compute_nlists(db, backbone_id, library_key)` that reads per-library `vector_group_size` from library doc (fallback to 15), sums hot+cold counts, and calls `compute_nlists` from `nomarr.helpers.vector_params_helper`; (e) calls `promote_and_rebuild_workflow(db, backbone_id, library_key, nlists, models_dir)` inside try/finally that always releases lock; (f) returns count of targets promoted.
    **Notes:** Added _compute_nlists (reads per-library vector_group_size, sums hot+cold, delegates to compute_nlists) and run_idle_promotion (stale lock reap, per-target lock/promote/release cycle with try/finally). Fixed RUF002 en-dash in docstring. Lint clean.
- [x] Run `lint_project_backend(path="nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py")` and fix all errors.
    **Notes:** lint_project_backend(path="nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py") — 0 errors.

### Phase 3: Worker Loop Integration
- [x] Add `IDLE_POLLS_BEFORE_PROMOTION: int = 3` module-level constant near existing constants in `discovery_worker.py`. Add `idle_consecutive_polls: int = 0` and `promotion_running: threading.Thread | None = None` in `run()` alongside existing tracking variables.
    **Notes:** Added IDLE_POLLS_BEFORE_PROMOTION=3 at line 38 (module-level). Added idle_consecutive_polls and promotion_running at lines 352-353 (run() tracking vars). F841 unused warnings expected — resolved in P3-S2 when these are wired into the idle branch.
- [x] In the idle branch (`file_id is None`): increment `idle_consecutive_polls` **as the first statement** (before cache eviction block and `time.sleep`). Reset `idle_consecutive_polls = 0` at top of the work-found path (immediately after non-None file_id confirmed). After the cache eviction block, before `time.sleep(IDLE_SLEEP_S)`: if `idle_consecutive_polls >= IDLE_POLLS_BEFORE_PROMOTION` and (`promotion_running is None` or `not promotion_running.is_alive()`), import `run_idle_promotion` from `nomarr.components.ml.vectors.ml_vector_idle_promotion_comp`, spawn `threading.Thread(target=run_idle_promotion, args=(db, self.worker_id, config.models_dir), daemon=True)`, assign to `promotion_running`, start it, log `[%s] Spawning idle vector promotion thread` at INFO level.
    **Notes:** Applied 3 replacements: (1) idle_consecutive_polls += 1 as first statement in idle branch at line 382; (2) promotion thread spawning block at lines 399-415 after cache eviction, before time.sleep; (3) idle_consecutive_polls = 0 reset at line 421 in work-found path. Lint clean.
- [x] In the existing `finally` block, after write executor shutdown: if `promotion_running is not None and promotion_running.is_alive()`, call `promotion_running.join(timeout=60)` to avoid abandoning an in-progress drain mid-operation during shutdown.
    **Notes:** Added promotion_running.join(timeout=60) at lines 621-623 in finally block, after write_executor.shutdown(wait=True). Lint clean.
- [x] Run `lint_project_backend(path="nomarr/services/infrastructure/workers/discovery_worker.py")` and fix all errors.
    **Notes:** lint_project_backend(path="nomarr/services/infrastructure/workers/discovery_worker.py") — 0 errors.

### Phase 4: Tests
- [x] Write unit tests in `tests/unit/components/ml/vectors/test_ml_vector_idle_promotion_comp.py`: test `list_hot_vector_targets` by mocking `discover_backbones` to return multiple backbones, `db.libraries.list_libraries` to return libraries, `db.db.has_collection` and `count()` — verify correct (backbone, library_key) pairing and filtering of empty collections. Test `run_idle_promotion` by mocking lock acquire returning True/False, mocking `promote_and_rebuild_workflow`, verifying lock is always released in `finally` even when the workflow raises.
- [x] Write unit tests in `tests/unit/persistence/database/test_vector_promotion_lock_aql.py` for `try_acquire_lock` verifying AQL INSERT with `ignoreErrors` is called correctly, and `release_lock` verifying the `locked_by` guard.
- [x] Run `lint_project_backend()` with no path (full workspace) to confirm zero errors.

## Completion Criteria

- After a scan finishes and workers enter idle state, vector similarity search begins working
  within ~5 seconds (3 idle polls × 1s + promotion time) without operator intervention.
- Promotion iterates all (backbone_id, library_key) combinations with pending hot vectors —
  per-library vector split (V018) is fully supported.
- Multiple idle workers coordinate via DB lock: exactly one runs promotion per backbone+library;
  others skip the locked target cleanly.
- A worker resuming tagging (new files arrive) is not blocked by a running promotion thread
  (daemon=True, fire-and-forget).
- A promotion lock left by a crashed worker auto-expires after 10 minutes and is reclaimed by
  the next idle worker.
- `promote_and_rebuild_workflow`'s existing idempotency guarantee is preserved: running promotion
  when hot is already empty and cold has index is a fast no-op.
- `compute_nlists` from `nomarr/helpers/vector_params_helper` remains the single source of truth
  for nlists sizing — no duplicated formula.
- `lint_project_backend()` reports zero errors after all changes.

## References

- `nomarr/services/infrastructure/workers/discovery_worker.py` — worker loop and idle detection
- `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py` — promotion + rebuild orchestration
- `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py` — drain/index primitives
- `nomarr/components/ml/vectors/ml_vector_persist_comp.py` — hot write path
- `nomarr/components/ml/onnx/ml_discovery_comp.py` — `discover_backbones()` for backbone enumeration
- `nomarr/persistence/database/vectors_track_aql.py` — `VectorsTrackHotOperations.count()`
- `nomarr/helpers/vector_params_helper.py` — `compute_nlists()` shared nlists formula
- `nomarr/services/domain/vector_maintenance_svc.py` — `VectorMaintenanceService` (already delegates to helper)
- `nomarr/migrations/V018_split_vectors_per_library.py` — latest migration (per-library vector split)
