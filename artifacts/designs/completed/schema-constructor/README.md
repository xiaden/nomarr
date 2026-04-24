# Constructor Completion — Implementation Parts

**Design Document:** [DD-constructor-completion](../../pending/DD-constructor-completion.md)  
**Governing ADRs:** [ADR-003](../../../decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md), [ADR-025](../../../decisions/ADR-025-persistence-constructor-rules.md)  
**Driving ASRs:** ASR-013 (complete API surface)  
**Scope:** Fix verb signatures (always-list), add missing verb capabilities, eliminate all raw AQL in components, delete legacy AQL files  
**Supersedes:** Previous Plans A–E (archived to `artifacts/plans/deprecated/`)

---

## Parts

 | Part | Title | Depends On | Layers | Estimated Steps |
 | ------ | ------- | ------------ | -------- | ---------------- |
 | A | Always-List Signatures + Compound Upsert | None | persistence | 10 |
 | B | Multi-Field Filter + Filtered Aggregate/Collect | A | persistence | 10 |
 | C | Raw AQL Elimination — Tags | A, B | components (tagging) | 12 |
 | D1 | Raw AQL Elimination — Library (Schema Caps + Mutation) | A, B | persistence, components (library) | 8 |
 | D2 | Raw AQL Elimination — Library (State) | D1 | components (library) | 12 |
 | D3 | Raw AQL Elimination — Library (Query) | D2 | components (library) | 12 |
 | E | Raw AQL Elimination — Analytics + ML | A, B | components (analytics, ml) | 10 |
 | F | Cleanup — Delete Legacy AQL + Update Docs | C, D3, E | persistence, artifacts | 8 |

---

## Dependency Graph

```
  ┌─────┐
  │  A  │  Always-List + Compound Upsert
  └──┬──┘
  ┌──▼──┐
  │  B  │  Multi-Field Filter + Filtered Agg/Collect
  └──┬──┘
  ┌──┴──────┬──────────┐
┌─▼──┐   ┌──▼──┐   ┌──▼──┐
│  C │   │ D1  │   │  E  │   (tags, library-caps+mutation, analytics+ML — parallel)
└──┬─┘   └──┬──┘   └──┬──┘
   │      ┌──▼──┐      │
   │      │ D2  │      │   (state migration)
   │      └──┬──┘      │
   │      ┌──▼──┐      │
   │      │ D3  │      │   (query migration)
   │      └──┬──┘      │
   └────┬────┴────┬────┘
     ┌──▼──┐
     │  F  │  Cleanup
     └─────┘
```

---

## Execution Rounds

```
Round 1: A              (verb signatures + compound upsert — persistence only)
Round 2: B              (multi-field filter + filtered agg/collect — persistence only)
Round 3: C, D1, E       (raw AQL elimination in tags, library-caps+mutation, analytics+ML — can run in parallel)
Round 4: D2             (library state migration — depends on D1)
Round 5: D3             (library query migration — depends on D2)
Round 6: F              (delete legacy files, update artifacts)
```

---

## Per-Part Scope

### Part A: Always-List Signatures + Compound Upsert

Change all mutation verbs from `T | list[T]` unions to `list[T]`-only. Remove isinstance dispatch. Update verb, namespace, and stub signatures. Extend `upsert_by_field` to accept `field: str | list[str]` for compound key matching. Update Rule 6 in CONTRACTS.md. Fix all existing callers (wrap scalars in `[]`, handle `list[str]` returns). Run full test suite.

### Part B: Multi-Field Filter + Filtered Aggregate/Collect

Add `build_equality_filter()` to filters.py. Create `*_by_filter` verb variants (get, count, delete, update). Wire `by_filter` accessor on collection namespaces. Add optional `filter` kwarg to `collect_field` and `aggregate_field`. Update stubs. Unit tests for all new verbs.

### Part C: Raw AQL Elimination — Tags

Rewrite all raw AQL in `tag_write_comp.py` (~3 calls), `tag_query_comp.py` (~11 calls), `tag_cleanup_comp.py` (~2 calls), `tag_stats_comp.py` (~8 calls). Validates compound-key upsert and filtered aggregate. Tags are the highest-coverage domain for new verb capabilities.

### Part D: Raw AQL Elimination — Library (Split into D1/D2/D3)

Rewrite all raw AQL in library component files. Split into three sequential sub-plans:

- **D1: Schema Caps + Mutation** — Add field capabilities to `file_has_state` and `library_contains_file` edge collections, then migrate `library_file_mutation_comp.py` (~5 calls). Runs in parallel with C and E.
- **D2: State Migration** — Migrate `library_file_state_comp.py` (~15 calls). Depends on D1 for schema capabilities.
- **D3: Query Migration** — Migrate `library_file_query_comp.py` (~28 calls, heaviest file). Category D queries (dynamic search, complex state queries) decompose into multi-verb compositions. Depends on D2.

### Part E: Raw AQL Elimination — Analytics + ML

Rewrite all raw AQL in `mood_analysis_comp.py` (~7 calls), `ml_calibration_comp.py` (~1 call), `ml_calibration_state_comp.py` (~4 db.db bypasses), `ml_vector_maintenance_comp.py` (~5 calls). `drain_hot_to_cold` becomes multi-verb composition. Bin math moves to Python.

### Part F: Cleanup

Delete all legacy AQL files in `persistence/database/` (directories: library_files_aql, tags_aql, vectors_track_aql; files: *_aql.py). Remove dead imports. Regenerate type stubs. Final CONTRACTS.md and MIGRATION-MAP.md updates. Full lint + test verification.

---

## Key Architectural Notes

- **100% schema-driven** — no hand-written AQL, no custom_ops escape hatch
- **Always-list** — mutation verbs accept `list[T]`, never scalar, never union
- **Runtime construction** — no build-time codegen, no committed generated files
- **All callers migrate** — no compatibility shims or wrappers
- **Mandatory pagination** on all unbounded-result verbs
- **Three-phase transition** — READ→REMOVE→INSERT per ADR-003 + ERR 1579
