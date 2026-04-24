# Background Task Standardization — Design Document

**Status:** Draft  
**Author:** rnd-manager  
**Created:** 2026-04-05  

**Related Documents:**

- [ADR-003](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — Boolean state graph for file processing pipeline
- [ADR-004](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Schema refactor v1 graph normalization
- [ADR-008](artifacts/decisions/ADR-008-two-phase-tag-writeback.md) — Two-phase tag writeback
- [ADR-013](artifacts/decisions/ADR-013-tagging-service-ownership.md) — Tagging service ownership
- [DD-ml-pipeline-automation](artifacts/designs/pending/DD-ml-pipeline-automation.md) — ML pipeline automation design (depends on this DD)

---

## Scope

### In Scope

- Fix two known bugs in `BackgroundTaskService` (race condition, duplicate `_task_order`)
- Create `ManagedTask` dataclass in helpers layer
- Extend `BackgroundTaskService` with `ManagedTask`-based API, `cancel_task()`, `on_complete` callbacks, daemon policy, duplicate-running guard
- Migrate library scan to `ManagedTask` dispatch
- Add `start_write_tags_background` to `TaggingService`
- Update `get_reconcile_status` to query BTS
- Update write-tags interface endpoint to fire-and-forget
- Update frontend API client, component handlers, and UI copy (fire-and-forget integration)
- Write tests for BTS lifecycle, TaggingService reconcile dispatch, and reconcile endpoint
- Update developer documentation (`workers.md`, `architecture.md`)
- *(Optional)* Migrate CalibrationService thread management to BTS
- *(Optional)* Migrate TaggingService apply thread to BTS

### Out of Scope

- **File watchers** (FileWatcherService): Long-lived infrastructure daemons with different lifecycle semantics (start-on-boot, stop-on-shutdown). Not unit-of-work tasks.
- **Vector promotion** (DiscoveryWorker): Worker-internal thread, not a pipeline stage. Managed by the worker process itself.
- **Health monitoring** (HealthMonitorService): Infrastructure daemon with existing stop_event. Already well-structured.
- **`multiprocessing.Process` workers**: GPU/ML work runs in separate processes for isolation. Different execution model entirely.
- **`asyncio.to_thread` in interfaces**: Async bridging between FastAPI and synchronous services. Stays as-is.
- **Retry/backoff logic**: Explicitly rejected (see Constraints). Tasks run once; retry is the caller's decision.

---

## Problem Statement

Nomarr has seven distinct background execution patterns across six services. Each manages its own thread lifecycle, progress tracking, and error handling with no shared vocabulary:

- **CalibrationService** spawns raw `threading.Thread` with a manual lock+dict progress tracker and a callback hook wired at composition root.
- **TaggingService** spawns another raw thread for calibration apply with a separate lock+dict progress tracker, no callback.
- **LibraryService** delegates to `BackgroundTaskService` for scans, but BTS has no callbacks, no cancellation, no stop_event, and two known bugs (race condition on status write, duplicate `_task_order` entries).
- **TaggingService.reconcile_library** is invoked via `asyncio.to_thread` from the interface layer — synchronous, blocks until one batch completes, no looping, no progress.
- **FileWatcherService**, **DiscoveryWorker**, and **HealthMonitorService** each manage their own daemon threads with bespoke lifecycle patterns.

This fragmentation creates concrete problems:

1. **No callback chaining.** The calibrate→apply→write-tags pipeline requires post-task hooks. Only calibration generation has one, wired ad-hoc.
2. **No cooperative cancellation.** `cancel_scan()` returns `False`. Calibration and apply have no cancel path at all.
3. **Inconsistent status querying.** `get_reconcile_status` hardcodes `in_progress=False`. Calibration status uses `thread.is_alive()`. Scan status uses BTS dict lookup. Three patterns for the same question.
4. **BTS bugs block pipeline automation.** The race condition (thread starts before status is written) means a fast-completing task can overwrite the "running" status. Duplicate `_task_order` entries cause eviction skew.
5. **write-tags is synchronous and single-batch.** Dispatching reconciliation as a background task requires looping until `remaining == 0`, which the current interface doesn't support.

The upcoming ML Pipeline Automation DD (DD-ml-pipeline-automation) needs a reliable task execution substrate for the calibrate→apply→write-tags chain. This DD provides it.

---

## Architecture

## Core Data Model

### ManagedTask Dataclass

Location: `nomarr/helpers/managed_task.py` (new file)

```python
import dataclasses
import threading
from collections.abc import Callable
from typing import Any


@dataclasses.dataclass
class ManagedTask:
    """Descriptor for a background task submitted to BackgroundTaskService."""

    task_id: str
    fn: Callable[[], Any]
    stop_event: threading.Event = dataclasses.field(default_factory=threading.Event)
    on_complete: Callable[[], None] | None = None
    daemon: bool = True
```

Design choices:

- **No `args`/`kwargs`**: Caller uses `functools.partial` or lambda to bind arguments. Eliminates type-safety ambiguity.
- **No `on_error`**: BTS logs exceptions loudly and re-raises. Domain services that need error recovery inspect BTS status after the fact.
- **No `progress_fn`**: Domain services own progress state (see Progress Ownership below).
- **`stop_event` defaulted**: Always available for cancellation, even if the task callable doesn't check it.
- **`on_complete` fires on success only**: If the task callable raises, `on_complete` is NOT called. If `on_complete` itself raises, BTS logs and swallows — original task is already marked complete.

### Extended BackgroundTaskService

Location: `nomarr/services/infrastructure/background_tasks_svc.py` (existing file)

#### New `start_task` signature

```python
def start_task(self, task: ManagedTask) -> str:
```

Replaces the current `start_task(task_id, task_fn, *args, **kwargs)`.

#### Behavioral changes

 | Behavior | Before | After |
 | ---------- | -------- | ------- |
 | Status write timing | After `thread.start()` (race) | Before `thread.start()` |
 | `_task_order` duplicates | Appends unconditionally | Removes existing entry before appending |
 | Duplicate running task_id | Silently overwrites | Raises `ValueError` |
 | Completed/errored task_id | N/A | Silently replaces (idempotent restart) |
 | Thread daemon flag | Always `True` | `task.daemon` field |
 | Callback on success | None | Calls `task.on_complete()` if set |
 | Stop event storage | None | Stored via `ManagedTask` in `_tasks` dict |

#### New internal storage

```python
# Replace: self._tasks: dict[str, threading.Thread]
# With:
self._tasks: dict[str, tuple[threading.Thread, ManagedTask]]
```

The `ManagedTask` is retained so `cancel_task` can access `stop_event` and `get_task_status` can report daemon mode.

#### `cancel_task` (new method)

```python
def cancel_task(self, task_id: str) -> bool:
    """Signal a task to stop. Returns True if task was running."""
    with self._lock:
        entry = self._tasks.get(task_id)
        if not entry:
            return False
        thread, managed = entry
        if not thread.is_alive():
            return False
        managed.stop_event.set()
        return True
```

Signal-and-move-on: sets the event but does NOT `thread.join()`. Task self-terminates at its next checkpoint.

#### Wrapper function changes

```python
def wrapper() -> None:
    try:
        result = task.fn()
        with self._lock:
            self._task_results[task.task_id] = {
                "status": "complete",
                "result": result,
                "error": None,
            }
        if task.on_complete:
            try:
                task.on_complete()
            except Exception as cb_err:
                logger.error(f"on_complete callback failed for {task.task_id}: {cb_err}", exc_info=True)
    except Exception as e:
        logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
        with self._lock:
            self._task_results[task.task_id] = {
                "status": "error",
                "result": None,
                "error": str(e),
            }
        raise
```

Note: `on_complete` runs AFTER status is written as "complete", outside the lock.

---

## Daemon Policy

 | Operation | daemon | Rationale |
 | ----------- | -------- | ----------- |
 | Calibration generation | `False` | Long-running GPU work; don't lose progress on graceful shutdown |
 | Calibration apply | `False` | Writes to DB; incomplete apply leaves inconsistent state |
 | Library scan (quick/full) | `True` | Current behavior preserved; scan can resume on restart |
 | Write-tags to files | `True` | DB claims survive restart; incomplete batch is re-claimable via claim/release |

---

## Cancellation Protocol

**Pattern:** Signal-and-move-on. Caller calls `bts.cancel_task(task_id)` → returns immediately. Task callable must cooperatively check `stop_event.is_set()` at checkpoints.

**Minimum viable checkpoints (this DD):**

- `reconcile_library` inner per-file loop: `if stop_event.is_set(): break` before processing each file
- `apply_calibration_wf` between files: check at the natural per-file progress-update boundary
- Calibration generation: stop_event is wired but NOT checked inside the callable (too invasive; defer to future work)
- Library scan: stop_event is wired but NOT checked (scan is fast per-batch; cancel semantics are "don't start next batch")

**What cancel does NOT do:**

- Does not `thread.join()` — avoids blocking the caller
- Does not force-kill the thread — Python doesn't support this safely
- Does not guarantee immediate termination — task finishes current unit of work first
- Does not mark the task as "cancelled" — tasks are marked "complete" after reaching their cancellation checkpoint. The per-file claim/lease mechanism (60-second expiry) provides idempotent re-triggering without a separate cancelled state.

**Batch cancellation:** Cancelling all active tasks for a library is handled by calling `cancel_task(task_id)` for each known task ID. BTS provides no batch-cancel convenience method — this is deferred to the Pipeline Automation DD, which will define task-naming conventions and cancellation scope.

---

## Progress Ownership

Domain services **continue to own progress state**. BTS does NOT hold a generic progress dict.

**Rationale:** `CalibrationService.get_generation_progress()` has two code paths — a running path (reads in-memory dict under lock) and an idle path (queries DB for stored calibration state). Both are domain-specific. Pushing this into BTS would either duplicate the domain logic or require BTS to understand calibration semantics.

**After migration, domain services may:**

- Replace `thread.is_alive()` checks with `bts.get_task_status(task_id)["status"] == "running"`
- Keep their progress dicts and locks for fine-grained progress (e.g., `processed / total` counts)
- Query BTS for coarse status ("running", "complete", "error") and own progress dict for detailed status

---

## write_tags_to_files Migration

### New method on TaggingService

```python
def start_write_tags_background(
    self,
    library_id: str,
    stop_event: threading.Event,
    on_complete: Callable[[], None] | None = None,
) -> str:
    """Dispatch background write-tags loop for a library."""
    task_id = f"write_tags:{library_id}"

    def _task() -> None:
        while not stop_event.is_set():
            result = self.reconcile_library(library_id)
            if result.remaining == 0:
                break

    return self._bts.start_task(ManagedTask(
        task_id=task_id,
        fn=_task,
        stop_event=stop_event,
        on_complete=on_complete,
        daemon=True,
    ))
```

**Key behavior:** Loops until `remaining == 0` or cancelled. Each iteration processes one batch (default 100 files). The inner `reconcile_library` call uses the existing claim/release mechanism for per-file error isolation.

### TaggingService constructor change

```python
# Add BTS as constructor dependency
def __init__(
    self,
    db: Database,
    cfg: NomarrConfig,
    config_service: ConfigService,
    library_service: LibraryService,
    bts: BackgroundTaskService,   # NEW
) -> None:
    ...
    self._bts = bts
```

Wired in `app.py` composition root.

### Interface endpoint change

`POST /library/{id}/write-tags` changes from synchronous to fire-and-forget:

**Before:** Blocks until one batch completes, returns `ReconcileTagsResult`.
**After:** Dispatches background task, returns `{"status": "started", "task_id": "write_tags:{library_id}"}`.

This is a **breaking API change**. Frontend must be updated to poll `GET /library/{id}/reconcile-status`.

### get_reconcile_status update

```python
def get_reconcile_status(self, library_id: str) -> dict[str, Any]:
    library = self.db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library not found: {library_id}")

    pending_count = self.db.library_files.count_files_needing_reconciliation(
        library_id=library_id,
    )

    task_status = self._bts.get_task_status(f"write_tags:{library_id}")
    in_progress = task_status is not None and task_status["status"] == "running"

    return {
        "pending_count": pending_count,
        "in_progress": in_progress,
    }
```

### commit_pending_tags: NO CHANGE

`commit_pending_tags` calls `reconcile_library` synchronously via `asyncio.to_thread`. This is by design (ADR-008: tag curation commit is synchronous from the user's perspective). Do NOT migrate to background dispatch.

---

## Concurrent Task Safety

**Per-library isolation:** Task IDs are namespaced per library (e.g., `write_tags:libraries/123`, `scan:libraries/123`). BTS rejects duplicate running task_ids, preventing concurrent write-tags for the same library.

**Cross-type hazard:** `commit_pending_tags` and a background `write_tags` task can run concurrently for the same library. Both call `reconcile_library`, which uses claim-based file locking (`claim_files_for_reconciliation` with `worker_id`). Different worker_ids means different claims — they process disjoint file sets. This is safe by design.

**Concurrent scan + write-tags:** A library scan discovering new files and adding new `tags_stale` records while a `write_tags` task is running is also safe. Newly created state records are unclaimed — the write-tags loop's `remaining == 0` termination condition naturally picks them up in subsequent iterations. Stale-path failures (file moved since the DB record was written) are handled per-file: the claim is released, the result is logged as failed, and the file stays `tags_stale` until the next scan updates the path. The batch never aborts.

---

## What Stays Unchanged

 | Component | Why |
 | ----------- | ----- |
 | `commit_pending_tags` | Synchronous by design (ADR-008) |
 | FileWatcherService threads | Infrastructure daemon, not unit-of-work task |
 | DiscoveryWorker promotion thread | Worker-internal concern |
 | HealthMonitorService thread | Infrastructure daemon with stop_event already |
 | `multiprocessing.Process` workers | GPU/ML isolation, different lifecycle |
 | `asyncio.to_thread` in interfaces | Async bridging layer, stays as-is |
 | CalibrationService progress dicts | Domain-specific, not BTS concern |
 | TaggingService apply progress dicts | Domain-specific, not BTS concern |

---

## Design Goals

1. **Simple, not a framework.** One dataclass, one service, no registry, no plugin system. The full pattern fits in a developer's head.
2. **Callback chaining without coupling.** `on_complete` enables calibrate→apply→write-tags without services importing each other. The composition root wires the chain.
3. **Cooperative cancellation.** `stop_event` + signal-and-move-on. No force-kill, no join, no timeout. Task owns its exit timing.
4. **Per-library task isolation.** Task IDs are namespaced per library. BTS prevents duplicate running tasks with the same ID.
5. **Progress stays in the domain.** BTS provides coarse status (running/complete/error). Domain services provide fine-grained progress. No leaky abstraction.
6. **Fix before extend.** BTS bugs are fixed first, before any new features are added. Migration happens on a solid foundation.
7. **Backward-compatible where possible.** Only the write-tags endpoint is a breaking change. All other existing callers adapt internally without API surface changes.

---

## Constraints

### From ADRs

- **ADR-003 (Boolean state graph):** Pipeline state lives in `library_pipeline_states` / `library_has_pipeline_state` edges. Background tasks do NOT thread `calibration_hash`, `target_mode`, or `write_mode` through call chains — they read current state from DB at execution time.
- **ADR-004 (Graph normalization):** Library/file relations are normalized edges. Scan state is in `library_scans`, not on library documents.
- **ADR-008 (Two-phase writeback):** Tag writeback is DB curation first, file writeback second. Per-file failures don't block other files. `commit_pending_tags` is synchronous and must NOT be migrated to background dispatch.
- **ADR-013 (TaggingService ownership):** `TaggingService` is the single owner for all tag-domain operations including write-tags. New background methods live on `TaggingService`, not on a separate task service.

### Architectural

- **No asyncio in domain services.** Domain services are synchronous. Background execution uses `threading.Thread` managed by BTS.
- **No retry/backoff.** The abandoned `PipelineAutomationService` poll-based design with exponential backoff was rejected. Tasks run once. If they fail, status is "error". Retry is the caller's decision.
- **No global state.** `ManagedTask` is a value object. BTS stores instances by task_id, but tasks don't share mutable state.
- **Dependency direction preserved.** BTS is infrastructure. Services receive BTS via DI. BTS does not import domain services.

---

## Migration Order

**Ordering rationale:** Fix bugs before building on them, then maximize parallelism. Interface and frontend changes land last so internal contracts stabilize before breaking callers.

**Critical path:** Steps 1+2 (parallel) → 3 → 5 → 6 → 7

 | Phase | Steps | Constraint |
 | ------- | ------- | ----------- |
 | A | 1, 2 | Independent — can execute in parallel |
 | B | 3 | Blocked on both 1 and 2 |
 | C | 4, 5, 8, 9 | All blocked on 3 only — can execute in parallel |
 | D | 6 | Blocked on 5 |
 | E | 7 | Blocked on 6 |

---

**Steps 1 and 2 can be executed in parallel — they touch disjoint code.**

**Step 1: Fix BTS bugs**

- Fix the race condition: write `"running"` status to `_task_results` *before* calling `thread.start()`, not after ([background_tasks_svc.py](nomarr/services/infrastructure/background_tasks_svc.py) lines 94–105)
- Fix `_task_order` duplicates: guard `self._task_order.append(task_id)` with a prior removal if the task_id already exists (line 73)
- *Test milestone: Existing BTS callers (`scan.py`) still pass. Manual verification: rapid double-start of same `task_id` does not duplicate `_task_order`.*

**Step 2: Add `ManagedTask` dataclass**

- Create `nomarr/helpers/managed_task.py` — pure data, zero integration
- *Test milestone: Unit test: instantiation, defaults, `stop_event` starts unset.*

**Step 3: Extend `BackgroundTaskService` (depends on 1 AND 2)**

- New `start_task(task: ManagedTask)` signature replacing current `start_task(task_id, task_fn, *args, **kwargs)`
- Add `cancel_task(task_id: str) -> bool`
- Add duplicate-running guard (raise `ValueError` if same `task_id` is already `"running"`)
- Wire `task.daemon` and `task.on_complete`
- *Test milestone: Unit tests for start/cancel lifecycle, duplicate rejection, `on_complete` fires on success, daemon flag propagates.*

---

**After Step 3, Steps 4, 5, 8, and 9 can all execute in parallel.**

**Step 4: Migrate `LibraryScanMixin` (depends on 3)**

- Update both call sites in `nomarr/services/domain/library_svc/scan.py` (lines 97–106 and 135–145) to construct `ManagedTask` objects and use the new `start_task()` signature
- Scan tasks use `daemon=True`
- *Test milestone: Library scan starts and completes via new API. Existing scan integration tests pass.*

**Step 5: Add `start_write_tags_background` to `TaggingService` (depends on 3)**

- New looping method on `TaggingService`; add `background_tasks: BackgroundTaskService` as constructor parameter
- Wire BTS in `app.py` line 335 (`background_tasks` is already in scope at that line)
- Update `get_reconcile_status` to query `bts.get_task_status(f"write_tags:{library_id}")` for `in_progress`
- *Test milestone: Unit test: calling `start_write_tags_background` registers a task in BTS. Cancelling it sets the stop event. `get_reconcile_status` reflects running/idle correctly.*

**Step 6: Update interface + response types (depends on 5)**

- Change `reconcile_library_tags` endpoint from synchronous to fire-and-forget (returns `{"status": "started", "task_id": "..."}` immediately)
- Update `library_types.py` response models
- *Test milestone: API test: POST reconcile returns 202 with task_id. GET reconcile-status returns correct `in_progress` state.*

**Step 7: Update frontend (depends on 6)**

**API layer (`frontend/src/shared/api/library.ts`, `frontend/src/shared/api/index.ts`):**

- Replace `ReconcileTagsResult` interface (`{ processed, remaining, failed }`) with `StartTagWriteResult` (`{ status: "started"; task_id: string }`)
- Update `reconcileTags()` return type from `Promise<ReconcileTagsResult>` to `Promise<StartTagWriteResult>`
- Update barrel re-export in `index.ts` (currently re-exports `ReconcileTagsResult` at line 31)

**Component changes (`frontend/src/features/library/components/LibraryManagement.tsx`):**

- Update `handleReconcileTags` — receives `{ status: "started", task_id }` instead of batch counts; success toast changes to `"Tag write started"`
- Add polling infrastructure: after dispatch, poll `getReconcileStatus()` on an interval until `in_progress: false`, then clear `reconcilingId` loading state. Analogous to the `setInterval`/`useEffect` pattern in `frontend/src/features/tag-curation/hooks/usePendingCommit.ts`
- Write-mode-change confirm dialog (lines 315–320) calls the same handler — semantics change automatically; dialog copy updated below

**UI copy — rename all "reconcile" to "write tags":**

 | Current string | Replacement |
 | --- | --- |
 | `"Reconcile Tags?"` (dialog title) | `"Write Tags?"` |
 | `"...Reconcile now?"` (dialog message) | `"...Write tags now?"` |
 | `"Reconciled ${result.processed} files..."` (success toast) | `"Tag write started"` |
 | `"Failed to reconcile tags"` (error) | `"Failed to start tag write"` |
 | `"Reconciling tags..."` (button tooltip, in-progress) | `"Writing tags..."` |
 | `"Reconciling..."` (button label, in-progress) | `"Writing tags..."` |
 | `"Reconcile Tags"` (button label, at rest) | `"Write Tags"` |

**Generated bundle:**

- Regenerate `nomarr/public_html/assets/index-*.js` after frontend source changes (tracked bundle currently embeds the old `reconcile-tags` URL at line 147)

*Test milestone: Frontend lint passes. `reconcileTags()` compiles against the new `StartTagWriteResult` type. Manual: trigger write-tags, loading state persists until `in_progress: false`, then clears.*

---

**Optional steps (depend on 3, independent of critical path):**

**Step 8 (Optional): Migrate `CalibrationService` threads to BTS**

- Replace manual thread lifecycle in `nomarr/services/domain/calibration_svc.py` with `ManagedTask` + `start_task()`
- Retain `_post_generation_hook`/`_progress` structures (domain-owned, not BTS concern)
- *Test milestone: Calibration start/cancel works through BTS. Existing calibration tests pass.*

**Step 9 (Optional): Migrate `TaggingService` apply thread to BTS**

- Replace manual thread management for the apply operation (`_apply_thread` at lines 100–104 of `tagging_svc.py`) with `ManagedTask` + `start_task()`
- *Test milestone: Apply start/cancel works through BTS. Existing apply tests pass.*

**Step 10: Write tests (depends on 3, 5, 6)**

*All test paths are net-new — no existing test files cover BTS, TaggingService reconcile dispatch, or the reconcile endpoint.*

- **`tests/unit/services/infrastructure/test_background_task_svc.py`** (new, HIGH):
  - `start_task()` lifecycle: status is "running" before thread finishes starting, then "complete" on exit — race-condition regression
  - Duplicate running `task_id` raises `ValueError`
  - `cancel_task()` signals `stop_event`, returns `True`; returns `False` for non-running task
  - `on_complete` fires after success, does NOT fire on error
  - `_task_order` eviction stays correct after multiple start/complete cycles

- **`tests/unit/services/domain/test_tagging_svc_reconcile.py`** (new, HIGH):
  - `start_write_tags_background()` registers a BTS task with `task_id = f"write_tags:{library_id}"`
  - `cancel_task()` sets the stop event and the task loop exits
  - `get_reconcile_status()` returns `in_progress: True` when BTS reports "running", `False` otherwise

- **`tests/integration/test_reconcile_endpoint.py`** (new, HIGH):
  - `POST /library/{id}/reconcile-tags` returns 202 with `{"status": "started", "task_id": "..."}` for a known library
  - Returns 404 for unknown library
  - `GET /library/{id}/reconcile-status` returns `{ pending_count: int, in_progress: bool }`

*Test milestone: All three new test files pass. `pytest tests/unit/services/infrastructure/test_background_task_svc.py -v` green.*

**Step 11: Update developer docs (depends on 6)**

- **`docs/dev/workers.md`** — add "Background Tasks (BTS)" section:
  - Distinguish BTS `threading.Thread` tasks from `multiprocessing.Process` DiscoveryWorker
  - Document `ManagedTask` API: `task_id`, `stop_event`, `on_complete`, `daemon`
  - Use the write-tags reconcile flow as the canonical BTS dispatch example
  - Describe the cancellation protocol (signal-and-move-on, cooperative `stop_event.is_set()` checks)

- **`docs/dev/architecture.md`** — add write-tags data flow:
  - Fire-and-forget path: `POST /library/{id}/reconcile-tags → TaggingService.start_write_tags_background() → BTS.start_task() → reconcile loop`
  - Polling path: `GET /library/{id}/reconcile-status → TaggingService.get_reconcile_status() → BTS.get_task_status()`
  - Note BTS as the infrastructure layer between interface handlers and domain services

*Test milestone: `mkdocs build` runs without errors.*

---

## Breaking Changes

### `POST /library/{id}/reconcile-tags` (write-tags endpoint)

 | | Before | After |
 | --- | --- | --- |
 | Behavior | Synchronous: blocks until one batch completes | Fire-and-forget: dispatches background task, returns immediately |
 | Response body | `ReconcileTagsResult` (`processed`, `remaining`, `failed`) | `{"status": "started", "task_id": "write_tags:{library_id}"}` |
 | Navidrome rescan | Triggered inline after completion | Triggered via `on_complete` callback after background loop finishes |
 | Frontend impact | Success message shows per-batch counts; all UI copy uses "Reconcile Tags" terminology | Success toast changes to "Tag write started"; all UI copy renamed to "Write Tags"; loading state driven by polling until `in_progress: false` |

Frontend files requiring update:

- `frontend/src/shared/api/library.ts` — `ReconcileTagsResult` → `StartTagWriteResult`, `reconcileTags()` return type
- `frontend/src/shared/api/index.ts` — barrel re-export updated
- `frontend/src/features/library/components/LibraryManagement.tsx` — handler semantics, 7 UI copy strings, polling infrastructure (new)
- `nomarr/public_html/assets/index-*.js` — regenerate after frontend source changes

No other public API surface changes. `GET /library/{id}/reconcile-status` shape is unchanged (same fields, `in_progress` is now accurate).

---

## Resolved Design Questions

All four open questions raised during initial drafting have been resolved through code analysis.

### Q1: Concurrent scan + write-tags safety

**Resolved: Safe. No coordination mechanism needed.**

Traced via `write_file_tags_workflow`, `reconcile_library`, and `claim_files_for_reconciliation`:

- Scans adding new `tags_stale` records during a write-tags run create unclaimed records. The write-tags loop's `remaining == 0` termination naturally picks them up in subsequent iterations.
- File-moved failures are handled per-file: `_resolve_library_path(check_disk=True)` validates the path, failing gracefully with a logged `WriteResult`. The claim is released and the file stays `tags_stale` until the next scan updates the path.
- File deleted from disk: same path as moved — returns failed `WriteResult`, batch continues.
- DB record deleted between claim and write: `get_file_for_writing()` returns `None` → failed `WriteResult`. Orphaned claim is benign.
- Error strategy is log-and-continue per file. The batch never aborts.

These scenarios are already handled. No new scope items needed.

### Q2: "Cancelled" BTS status

**Resolved: Not needed. Removed from scope.**

Traced via `claim_files_for_reconciliation` (lease\_ms=60000) in `nomarr/persistence/database/library_files_aql/reconciliation.py`:

- Successfully processed files are `tags_current` (permanent).
- Unprocessed files remain `tags_stale` with active claims that auto-expire after 60 seconds.
- After expiry, the next trigger re-claims and processes remaining files without any manual cleanup.
- There is no library-level `write_ready` flag — per-file `tags_stale` state is the sole re-trigger driver.

A "cancelled" terminal state would have no consumer: the UI can infer "not running" from the absence of a `"running"` status, and re-triggering checks file state, not BTS status. If UI feedback requires a distinct cancelled state in the future, it can be added then.

### Q3: `cancel_all_tasks_for_prefix` — removed from scope

**Resolved: Remove. Per-task `cancel_task(task_id)` is sufficient for this DD.**

The motivating use case (Pipeline Automation cancelling all tasks for a library on deletion) doesn't exist yet. The name `prefix` is an implementation leak with no domain meaning. Any batch-cancel API belongs in the Pipeline Automation DD, which will define task-naming conventions. Adding it here forces vague conventions and creates an untestable contract with no callers.

Batch cancellation deferred to Pipeline Automation DD.

### Q4: CalibrationService migration priority / migration ordering

**Resolved: See Migration Order section.**

PatternEnforcer confirmed exactly 2 BTS call sites (both in `nomarr/services/domain/library_svc/scan.py`, lines 97–106 and 135–145), 1 TaggingService instantiation site (`app.py` line 335), and the full dependency graph. Steps 8–9 are independent of the critical path and remain optional — they do not block the Pipeline Automation DD.

---

## Complexity Estimate

**MEDIUM** — approximately 18 files.

 | Area | Size | Files |
 | --- | --- | --- |
 | Core backend (steps 1–6) | MEDIUM | ~7 files modified/created |
 | Frontend migration (step 7) | SMALL | ~4 files (3 source + regenerated bundle) |
 | Tests (step 10) | SMALL | 3 new files |
 | Docs (step 11) | SMALL | 2 files |
 | Optional cleanup (steps 8–9) | SMALL increment | ~1 additional file |

**Likely file list:**

*Core backend:*

- `nomarr/helpers/managed_task.py` (new)
- `nomarr/services/infrastructure/background_tasks_svc.py` (modified)
- `nomarr/services/domain/library_svc/scan.py` (modified)
- `nomarr/services/domain/tagging_svc.py` (modified)
- `nomarr/interfaces/api/web/library_if.py` (modified)
- `nomarr/interfaces/api/types/library_types.py` (modified — `ReconcileTagsResponse` → `StartTagWriteResponse`)
- `nomarr/app.py` (modified — BTS injected into TaggingService)

*Frontend:*

- `frontend/src/shared/api/library.ts` (modified)
- `frontend/src/shared/api/index.ts` (modified — re-export update)
- `frontend/src/features/library/components/LibraryManagement.tsx` (modified)
- `nomarr/public_html/assets/index-*.js` (regenerated bundle)

*Tests:*

- `tests/unit/services/infrastructure/test_background_task_svc.py` (new)
- `tests/unit/services/domain/test_tagging_svc_reconcile.py` (new)
- `tests/integration/test_reconcile_endpoint.py` (new)

*Docs:*

- `docs/dev/workers.md` (modified)
- `docs/dev/architecture.md` (modified)

**Notes:**

- `nomarr/helpers/dto/library_dto.py` defines `ReconcileTagsResult` and is used internally by `TaggingService`. The DTO is retained; only the HTTP response model in `library_types.py` changes.

**Risks:**

- `TaggingService.__init__` change touches `app.py` and test fixtures
- Polling infrastructure in `LibraryManagement.tsx` is entirely new — no existing pattern in this component (reference: `usePendingCommit.ts` in tag-curation)
- No existing tests cover BTS, TaggingService reconcile dispatch, or the reconcile endpoint — test work is mostly creation
- Optional steps 8–9 share `tagging_svc.py` with step 5 (one file counted in both core and optional)

---
