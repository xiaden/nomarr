# File Splitting Refactor — Implementation Parts

**Design Doc:** `artifacts/designs/pending/DD-file-splitting-refactor.md`
**ADR:** ADR-021 (File Length Limits Per Architecture Layer)

## Parts

 | Part | Title | Depends On | Layer | Split Type |
 | ------ | ------- | ------------ | ------- | ------------ |
 | A | Persistence subpackage (`file_states_aql`) | None | persistence | Mixin subpackage |
 | B | Tagging service mixin package (`tagging_svc`) | None | service | Mixin package |
 | C | Worker internal extraction (`discovery_worker` + `worker_system_svc`) | None | service | Same-file extraction |
 | D | Library interface router split (`library_if`) | None | interface | Router split |

## Dependency Graph

```
Round 1 (persistence):  [A]
Round 2 (services):     [B]  [C]
Round 3 (interfaces):   [D]
```

All parts are technically independent — no cross-plan data dependencies. The round ordering reflects the dependency direction (persistence → services → interfaces) to reduce risk of churn if a lower-layer split reveals issues.

## Execution Rounds

Round 1: A (persistence — heaviest split, most callers to verify)
Round 2: B, C (services — independent of each other)
Round 3: D (interfaces — touches test files, router wiring)

## Per-Part Scope

### Part A: Persistence Subpackage (`file_states_aql`)

Convert `file_states_aql.py` (981 lines) into a `file_states_aql/` subpackage following the `library_files_aql/` pattern. 5 mixin modules (`transitions.py`, `bulk.py`, `init.py`, `queries.py`, `reset.py`) plus `_constants.py` and `__init__.py`. All 4 external import sites continue to resolve via `__init__.py` re-exports.

### Part B: Tagging Service Mixin Package (`tagging_svc`)

Convert `tagging_svc.py` (790 lines) into a `tagging_svc/` mixin package following the `library_svc/` pattern. 4 mixin modules (`apply.py`, `write.py`, `curation.py`, `query.py`) plus `config.py` and `__init__.py`. All 15 external import sites continue to resolve via `__init__.py` re-exports.

### Part C: Worker Internal Extraction

Decompose `discovery_worker.py` `run()` method (425 lines → ~80 lines + 7 helpers) and extract 3 helpers from `worker_system_svc.py`. Same-file refactors only — no package conversion, no public API changes, no caller updates needed.

### Part D: Library Interface Router Split

Split `library_if.py` (754 lines) into 3 router files (`library_if.py`, `library_files_if.py`, `library_scan_if.py`). Update `router.py` to include all 3. Update 4 test files that import `library_if.router` directly.
