# Task: Replace ArangoDB-as-IPC for VRAM coordination with in-process multiprocessing primitives

## Problem Statement

VRAM admission control currently writes `vram_promises` documents to ArangoDB to coordinate GPU model placement across 1–3 worker processes. Before each GPU model load, a worker issues an AQL aggregate-sum transaction to check headroom and atomically insert a promise. On unload, it issues another AQL DELETE. On crash, the service owner issues an AQL bulk DELETE.

This is database-as-IPC. It adds 2 ArangoDB round-trips per model load/unload cycle and one bulk DELETE per worker death in exchange for shared state that could be held in multiprocessing primitives created by the parent `WorkerSystemService`, which already owns all workers in one process. The `vram_promises` collection has no retention value — it is purely ephemeral coordination state.

Key observations from code research:

- `WorkerSystemService` creates all `DiscoveryWorker` processes and holds `self._workers: list[DiscoveryWorker]`. It is the natural owner of the coordinator.
- `ml_worker_context_comp.py` already holds a per-process registry `(db, worker_id)` that is populated at worker startup and read by `BaseONNXModel`. Extending this to also carry a coordinator proxy costs nothing and removes `db` from the VRAM coordinator call chain entirely.
- `multiprocessing.Manager().dict()` + `multiprocessing.Lock()` provides the same atomicity as the AQL FILTER/INSERT transaction. The `Manager` process is created once by `WorkerSystemService` and survives worker crashes because it is owned by the parent.
- The 256 MB `_RESERVE_MB` safety buffer in `vram_promises_aql.py` must be preserved in the new coordinator.
- The `release_worker_promises` path is called from two places: the worker itself (graceful shutdown) and `WorkerSystemService.on_status_change("dead")` / `stop_all_workers()`. Both paths remain; the former reads the coordinator from the context module, the latter calls the coordinator object directly.
- `get_fleet_vram_state()` is used for post-warm logging in `discovery_worker.py`. Its return shape `{"promises": [...], "vram": {...}}` should be preserved; the list entries lose ArangoDB `_key`/`_id` fields but callers only access `worker_id`, `model_path`, `promised_mb`.

## Phases

### Phase 1: Implement `VramCoordinator` IPC class in `ml_vram_coordinator_comp.py`

- [ ] Add `VramCoordinator` class to `ml_vram_coordinator_comp.py` that owns a `multiprocessing.Manager` instance, a `DictProxy` keyed by `(worker_id, model_path)` mapping to `promised_mb: float`, and a `multiprocessing.Lock`
- [ ] Implement `VramCoordinator.try_register(worker_id, pid, model_path, promised_mb, total_mb, used_mb) -> bool` — acquires lock, sums all values in the dict, checks `(total_mb - used_mb) - sum_promised - _RESERVE_MB >= promised_mb`, upserts entry on success, releases lock, returns bool
- [ ] Implement `VramCoordinator.release(worker_id, model_path) -> None` — acquires lock, removes entry if present, releases lock
- [ ] Implement `VramCoordinator.release_all_for_worker(worker_id) -> int` — acquires lock, removes all entries whose key[0] == worker_id, returns count, releases lock
- [ ] Implement `VramCoordinator.get_all() -> list[dict]` — returns snapshot list of `{worker_id, model_path, promised_mb}` dicts (no lock needed for snapshot read)
- [ ] Add `VramCoordinator.shutdown() -> None` that calls `self._manager.shutdown()` for clean parent-process teardown
- [ ] Add module-level `create_vram_coordinator() -> VramCoordinator` factory that creates and starts the Manager
- [ ] Run `lint_project_backend(path="nomarr/components/ml/ml_vram_coordinator_comp.py")` — zero errors required

### Phase 2: Extend `ml_worker_context_comp` to carry the coordinator

- [ ] Add `_coordinator: VramCoordinator | None = None` module-level variable to `ml_worker_context_comp.py`
- [ ] Update `register_worker_context(db, worker_id, coordinator=None)` to also store `_coordinator`
- [ ] Update `get_worker_context()` return type to `tuple[Any, str, VramCoordinator | None] | None` — return `(_worker_db, _worker_id, _coordinator)`
- [ ] Update `clear_worker_context()` to also clear `_coordinator`
- [ ] Run `lint_project_backend(path="nomarr/components/ml/ml_worker_context_comp.py")` — zero errors required

### Phase 3: Update `ml_vram_coordinator_comp` public functions to drop the `db` parameter

- [ ] Rewrite `register_vram_promise(worker_id, pid, model_path, promised_mb) -> bool` — reads coordinator from `_worker_ctx.get_worker_context()` (third element), returns False if coordinator is None (probe/test context), otherwise delegates to `coordinator.try_register(...)` with fresh nvidia-smi readings
- [ ] Rewrite `release_vram_promise(worker_id, model_path) -> None` — reads coordinator from context, no-op if None
- [ ] Rewrite `get_fleet_vram_state() -> dict` — reads coordinator from context (or accept optional coordinator kwarg for the service-level logging path), returns `{"promises": coordinator.get_all(), "vram": get_vram_usage_mb()}`
- [ ] Rewrite `release_worker_promises(worker_id, coordinator=None) -> int` — if coordinator is provided (service-owner path), calls it directly; otherwise reads from context; no-op if neither available
- [ ] Run `lint_project_backend(path="nomarr/components/ml/ml_vram_coordinator_comp.py")` — zero errors required

### Phase 4: Update `ml_onnx_base.py` call sites

- [ ] In `BaseONNXModel.load()`, update `ctx` unpacking to handle 3-element tuple `(db, worker_id, coordinator)` — the coordinator element is not used here since `register_vram_promise` now reads it from context internally; remove `db` from `register_vram_promise(...)` call
- [ ] In `BaseONNXModel.unload()`, update `ctx` unpacking and remove `db` from `release_vram_promise(...)` call
- [ ] In `BaseONNXModel.run()` OOM path, update `ctx` unpacking (db is still needed for `update_model_vram_from_oom`)
- [ ] Run `lint_project_backend(path="nomarr/components/ml/ml_onnx_base.py")` — zero errors required

### Phase 5: Update `WorkerSystemService` to own and pass the `VramCoordinator`

- [ ] Add `self._vram_coordinator: VramCoordinator | None = None` to `WorkerSystemService.__init__`
- [ ] In `start_all_workers()`, call `self._vram_coordinator = create_vram_coordinator()` before the first worker is spawned
- [ ] Pass `vram_coordinator=self._vram_coordinator` to each `create_discovery_worker(...)` call
- [ ] Do the same in `_restart_worker()` — pass the existing `self._vram_coordinator`
- [ ] Replace `release_worker_promises(self.db, component_id)` in `on_status_change("dead")` with `self._vram_coordinator.release_all_for_worker(component_id)` guarded by `if self._vram_coordinator`
- [ ] Replace `release_worker_promises(self.db, worker.worker_id)` loop in `stop_all_workers()` with a single call per worker to `self._vram_coordinator.release_all_for_worker(worker.worker_id)`, then call `self._vram_coordinator.shutdown()` and set it to None
- [ ] Remove the import of `release_worker_promises` from `worker_system_svc.py` (no longer needed)
- [ ] Run `lint_project_backend(path="nomarr/services/infrastructure/worker_system_svc.py")` — zero errors required

### Phase 6: Update `DiscoveryWorker` to receive and register the coordinator

- [ ] Add `vram_coordinator: VramCoordinator | None = None` parameter to `DiscoveryWorker.__init__` and store as `self._vram_coordinator`
- [ ] Update `create_discovery_worker()` factory to accept and pass `vram_coordinator`
- [ ] In `DiscoveryWorker.run()`, pass `self._vram_coordinator` to `register_worker_context(db, self.worker_id, self._vram_coordinator)`
- [ ] Replace the startup `release_worker_promises(db, self.worker_id)` call with `self._vram_coordinator.release_all_for_worker(self.worker_id)` if coordinator is present (belt-and-suspenders: coordinator survives parent-side and handles crash cleanup, but the worker should still clear its own stale entries at startup)
- [ ] Replace the shutdown `release_worker_promises(db, self.worker_id)` call in the `finally` block with a direct coordinator call
- [ ] Update `get_fleet_vram_state(db)` call in the post-warm logging block to `get_fleet_vram_state()` (db no longer required)
- [ ] Run `lint_project_backend(path="nomarr/services/infrastructure/workers/discovery_worker.py")` — zero errors required

### Phase 7: Remove `vram_promises` from the persistence layer

- [ ] Delete `nomarr/persistence/database/vram_promises_aql.py`
- [ ] Remove `vram_promises: VramPromisesOperations` attribute from `nomarr/persistence/db.py` — remove instantiation in `__init__` and the import
- [ ] Remove `vram_promises` from the collection initialization / teardown code in the database setup module (locate via `list_project_directory_tree("nomarr/persistence")` then grep for `vram_promises`)
- [ ] Write a forward-only migration in `nomarr/migrations/` that drops the `vram_promises` collection if it exists — follow the pattern of existing migration files
- [ ] Run `lint_project_backend(path="nomarr/persistence")` — zero errors required

### Phase 8: Global lint and import cleanup

- [ ] Run `lint_project_backend()` (full workspace) — zero errors required
- [ ] Verify `locate_module_symbol("VramPromisesOperations")` returns zero matches (dead code fully removed)
- [ ] Verify `locate_module_symbol("vram_promises")` has no remaining references in Python source outside migration and tests
- [ ] Run existing architecture tests: `pytest tests/test_architecture_qc.py -x` — must pass

## Completion Criteria

- No Python file imports `VramPromisesOperations` or references `db.vram_promises`
- `vram_promises_aql.py` does not exist
- A migration exists that drops the `vram_promises` collection
- `register_vram_promise` and `release_vram_promise` make zero ArangoDB calls
- `WorkerSystemService` creates one `VramCoordinator` (backed by `multiprocessing.Manager`) per `start_all_workers()` invocation and shuts it down in `stop_all_workers()`
- Worker crash path (`on_status_change("dead")`) calls `self._vram_coordinator.release_all_for_worker(worker_id)` with no DB round-trip
- `lint_project_backend()` reports zero errors
- Tier selection, capacity probing, and worker count logic are unmodified

## References

- `nomarr/components/ml/ml_vram_coordinator_comp.py` — current DB-backed coordinator
- `nomarr/persistence/database/vram_promises_aql.py` — AQL operations being removed
- `nomarr/components/ml/ml_worker_context_comp.py` — process-local registry to extend
- `nomarr/components/ml/ml_onnx_base.py` — consumer of register/release
- `nomarr/services/infrastructure/worker_system_svc.py` — coordinator owner
- `nomarr/services/infrastructure/workers/discovery_worker.py` — worker that uses coordinator
