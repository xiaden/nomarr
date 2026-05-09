# Completion Manifest — Collection-First Query-Spec Persistence

**Design document:** `artifacts/designs/pending/DD-collection-first-query-spec-persistence.md`
**Parts README:** `artifacts/designs/parts/collection-first-query-spec-persistence/README.md`
**Contracts ledger:** `artifacts/designs/parts/collection-first-query-spec-persistence/CONTRACTS.md`
**Completed:** 2026-05-09

## Execution Summary

| Plan | Outcome | Review / Fix Notes |
| --- | --- | --- |
| A | DONE | Exec-Manager reported `DONE`; QA/Test/Docs analyzers `PASS`; detailed round count not preserved in current artifacts. |
| B | DONE | Implementation exists in code and tests; original post-execution ledger entry was missing and was reconstructed from implemented code after crash recovery. |
| C | DONE | 3 QA rounds, 2 fix cycles; all checks PASS. |
| D | DONE | 5 phases, 15 steps, 4 fix cycles; QA PASS on Round 5. |

## Design Deviations

- `StateGraphCollection.transition(...)` did **not** survive as a fully justified standalone architectural center; it remains only as a compatibility shim over `EdgeCollection.replace_targets(...)` while policy stays above persistence.
- Most vector-branded helpers were reclassified away from “special primitive” status. Only `ann_search(...)` clearly remained vector-native; `upsert_vector(...)`, `get_vector(...)`, and `get_vectors_by_file_ids(...)` were retained only as explicit transitional shims.
- `VectorCollection.delete_by_file_id(...)` and `delete_by_file_ids(...)` were removed entirely during Part D after caller migration.
- The persistence surface now enforces collection-first root availability at `Database` bind time and blocks higher layers from importing persistence collection/accessor internals directly.

## Key Decisions

- Collection-first operations are the normative persistence surface; field accessors are compatibility-only and may not grow.
- Query specs, capability families, template assets, and public API naming remain explicitly separated to avoid recreating the old overloaded verb model.
- True storage-native primitives are limited to graph-native maintenance/counting, edge-target replacement, and ANN search; orchestration-heavy helpers live in components/workflows.
- AQL validation is a first-class architectural concern with spec/template/bind validation and parse/explain coverage where infrastructure is available.

## Files Created / Modified

### Persistence

- `nomarr/persistence/query_specs.py`
- `nomarr/persistence/query_templates.py`
- `nomarr/persistence/aql_validation.py`
- `nomarr/persistence/accessors.py`
- `nomarr/persistence/collections_base.py`
- `nomarr/persistence/db.py`

### Components / Workflows / Services

- `nomarr/components/library/library_file_state_comp.py`
- `nomarr/components/library/library_admin_comp.py`
- `nomarr/components/ml/vectors/ml_vector_registry_comp.py`
- `nomarr/components/ml/vectors/ml_vector_persist_comp.py`
- `nomarr/components/ml/vectors/ml_vector_retrieve_comp.py`
- `nomarr/workflows/find_similar_tracks_wf.py`
- `nomarr/services/infrastructure/worker_system_svc.py`
- `nomarr/services/infrastructure/workers/discovery_worker.py`
- `nomarr/services/infrastructure/keys_svc.py`
- `nomarr/services/infrastructure/info_svc.py`
- `nomarr/services/infrastructure/health_monitor_svc.py`
- `nomarr/services/domain/tagging_svc/write.py`
- `nomarr/app.py`

### Tests / Enforcement

- `tests/unit/persistence/test_query_specs.py`
- `tests/unit/persistence/test_query_templates.py`
- `tests/unit/persistence/test_aql_validation.py`
- `tests/unit/persistence/test_accessors.py`
- `tests/unit/persistence/test_collections_base.py`
- `tests/unit/persistence/database/test_db.py`
- `tests/unit/persistence/test_persistence_enforcement.py`
- `tests/integration/test_persistence_aql_validation.py`
- `tests/unit/components/ml/vectors/test_ml_vector_persist_comp.py`
- `tests/unit/components/ml/vectors/test_ml_vector_retrieve_comp.py`
- `tests/unit/components/library/test_library_file_state_comp.py`
- `tests/test_architecture_qc.py`

### Project Configuration

- `pyproject.toml`

## Final Verification

- Part A reported: `1687` tests passed, `0` failed.
- Part C reported: persistence `411`, ml/vectors `38` (+ `1` skipped), library components `187`, workflows `90` all passing.
- Part D reported:
  - `1730` tests passed, `0` failed overall execution summary
  - `pytest tests/unit/persistence/ tests/unit/components/ml/vectors/ tests/test_architecture_qc.py tests/unit/persistence/test_persistence_enforcement.py -q` → `461 passed, 1 skipped`
  - `pytest tests/integration/test_persistence_aql_validation.py -q` → `1 passed, 3 skipped`
  - import-linter → `10 kept, 0 broken`

## Notes

- Part B’s ledger entry had to be reconstructed from the implemented code after crash recovery because the original execution note did not land in `CONTRACTS.md`.
- The contracts ledger now records the final Part C and Part D outcomes and should be treated as the authoritative post-implementation reference for this feature.